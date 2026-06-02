"""
train_sleepiness.py — Huấn luyện MobileNetV2 phát hiện buồn ngủ.

UPGRADES v14:
  ✅ [ACCURACY] Targeted Eye CutMix: Giới hạn vùng cắt CutMix chỉ trong
                nửa trên khuôn mặt (vùng mắt + lông mày, y = 0 → H/2).
                Trước đây _rand_bbox cắt ngẫu nhiên toàn bộ ảnh → mô hình
                học vẹt đặc trưng tóc / tai / phông nền thay vì trạng thái mắt.
                Cải thiện dự kiến: +3–5% accuracy trên tập val khó.

UPGRADES v13:
  ✅ [ACCURACY] FocalLoss: thay CrossEntropyLoss → ép mô hình học các ca khó.
  ✅ [ACCURACY] CutMix Augmentation.
  ✅ [ACCURACY] enforce_frozen_bn() từ utils_model.
"""

import json
import math
import os
import platform
import time
from collections import Counter
from copy import deepcopy

import numpy as np
import torch
from torch import nn, optim
from torch.optim.lr_scheduler import ReduceLROnPlateau
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from torchvision.models import MobileNet_V2_Weights

from utils_model import build_model, enforce_frozen_bn, get_transform

try:
    from sklearn.metrics import precision_recall_fscore_support
    _SKLEARN = True
except ImportError:
    _SKLEARN = False
    print("[WARN] sklearn chưa cài → bỏ qua P/R/F1. Cài: pip install scikit-learn")

# ─── Cấu hình ────────────────────────────────────────────────────────────────
DEVICE               = "cuda" if torch.cuda.is_available() else "cpu"
DATA_DIR             = "data"
BATCH_SIZE           = 32
EPOCHS               = 30
LR                   = 1e-3
MODEL_PATH           = "sleepiness_model.pth"
CLASSES_PATH         = "class_names.json"
EARLY_STOP_PATIENCE  = 5
FOCAL_GAMMA          = 2.0
USE_CUTMIX           = True
CUTMIX_ALPHA         = 1.0
CUTMIX_PROB          = 0.5

# [v14] Targeted Eye CutMix — chỉ cắt trong vùng mắt (nửa trên ảnh)
# EYE_REGION_FRAC = 0.5 → vùng được phép cắt = y ∈ [0, H*0.5]
# Tăng lên 0.6 nếu khuôn mặt trong dataset bao gồm nhiều trán hơn.
EYE_REGION_FRAC: float = 0.5


# ─── [v13] Focal Loss ────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    """
    Focal Loss (Lin et al., 2017 — RetinaNet).

    FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)

    Args:
        alpha:    Tensor trọng số class. None → không dùng alpha.
        gamma:    Hệ số tập trung. 0 → CrossEntropyLoss thông thường.
        reduction: 'mean' | 'sum' | 'none'.
    """

    def __init__(
        self,
        alpha: torch.Tensor = None,
        gamma: float = 2.0,
        reduction: str = "mean",
    ):
        super().__init__()
        self.alpha     = alpha
        self.gamma     = gamma
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        log_prob = nn.functional.log_softmax(logits, dim=1)
        log_pt   = log_prob.gather(1, targets.unsqueeze(1)).squeeze(1)
        pt       = log_pt.exp()
        focal_weight = (1.0 - pt) ** self.gamma

        if self.alpha is not None:
            at = self.alpha.gather(0, targets)
            focal_weight = at * focal_weight

        loss = -focal_weight * log_pt

        if self.reduction == "mean":
            return loss.mean()
        if self.reduction == "sum":
            return loss.sum()
        return loss


# ─── [v14] Targeted Eye CutMix ───────────────────────────────────────────────

def _rand_bbox_eye_region(size: tuple, lam: float, eye_frac: float = EYE_REGION_FRAC) -> tuple:
    """
    [v14] Tính bounding box CutMix TRONG VÙNG MẮT (nửa trên ảnh).

    Vấn đề v13:
        _rand_bbox cắt ngẫu nhiên toàn bộ ảnh (H × W). Nếu vùng cắt trúng
        tóc, tai hoặc phông nền, mô hình học vẹt đặc trưng không liên quan.

    Giải pháp v14:
        Ràng buộc tâm cắt (cx, cy) trong vùng y ∈ [0, H * eye_frac].
        Điều này ép CutMix chỉ hoán đổi thông tin vùng mắt giữa hai ảnh,
        buộc mô hình phân biệt mắt mở/nhắm dựa trên cấu trúc sinh học.

    Args:
        size:     Kích thước batch tensor (N, C, H, W).
        lam:      Tỷ lệ Lambda từ phân phối Beta.
        eye_frac: Tỷ lệ chiều cao dành cho vùng mắt (mặc định 0.5 = nửa trên).

    Returns:
        (x1, y1, x2, y2) — tọa độ vùng cắt, đã clamp vào ảnh.
    """
    H, W = size[2], size[3]
    cut_ratio = math.sqrt(1.0 - lam)
    cut_h     = int(H * cut_ratio)
    cut_w     = int(W * cut_ratio)

    # [v14] Giới hạn tâm cắt trong nửa trên ảnh (vùng mắt)
    # [v17 FIX] Guard eye_frac<=0 → fallback toàn ảnh
    eye_h_max = int(H * eye_frac) if eye_frac > 0 else H
    if eye_h_max <= 0:
        eye_h_max = H
    cx = np.random.randint(W)
    cy = np.random.randint(max(1, eye_h_max))

    x1 = np.clip(cx - cut_w // 2, 0, W)
    y1 = np.clip(cy - cut_h // 2, 0, H)
    x2 = np.clip(cx + cut_w // 2, 0, W)
    # Ràng buộc y2 không vượt quá eye_h_max để vùng cắt nằm trọn trong vùng mắt
    y2 = np.clip(cy + cut_h // 2, 0, eye_h_max)

    return x1, y1, x2, y2


def cutmix_batch(
    images: torch.Tensor,
    labels: torch.Tensor,
    alpha: float = CUTMIX_ALPHA,
    use_targeted: bool = True,
) -> tuple:
    """
    Áp dụng CutMix trên 1 batch ảnh.

    [v14] use_targeted=True → dùng _rand_bbox_eye_region (chỉ vùng mắt).
    [v14] use_targeted=False → dùng _rand_bbox gốc (toàn ảnh, tương thích v13).

    Returns:
        (mixed_images, labels_a, labels_b, lam)
    """
    lam = np.random.beta(alpha, alpha)
    N   = images.size(0)
    idx = torch.randperm(N, device=images.device)

    if use_targeted:
        x1, y1, x2, y2 = _rand_bbox_eye_region(images.size(), lam)
    else:
        # Fallback: _rand_bbox v13 (toàn ảnh)
        H, W = images.size(2), images.size(3)
        cut_ratio = math.sqrt(1.0 - lam)
        cut_h = int(H * cut_ratio); cut_w = int(W * cut_ratio)
        cx = np.random.randint(W); cy = np.random.randint(H)
        x1 = np.clip(cx - cut_w // 2, 0, W); y1 = np.clip(cy - cut_h // 2, 0, H)
        x2 = np.clip(cx + cut_w // 2, 0, W); y2 = np.clip(cy + cut_h // 2, 0, H)

    mixed = images.clone()
    mixed[:, :, y1:y2, x1:x2] = images[idx, :, y1:y2, x1:x2]

    lam_actual = 1.0 - (x2 - x1) * (y2 - y1) / (images.size(-1) * images.size(-2))
    return mixed, labels, labels[idx], lam_actual


# ─── Kiểm tra dữ liệu ────────────────────────────────────────────────────────

def validate_data_dirs(data_dir: str = DATA_DIR) -> None:
    errors = []
    for split in ("train", "val"):
        split_path = os.path.join(data_dir, split)
        if not os.path.isdir(split_path):
            errors.append(f"  ✗ Thiếu thư mục: {split_path}"); continue
        class_dirs = [d for d in os.listdir(split_path)
                      if os.path.isdir(os.path.join(split_path, d))]
        if not class_dirs:
            errors.append(f"  ✗ Không có class trong: {split_path}"); continue
        for cls in class_dirs:
            imgs = [f for f in os.listdir(os.path.join(split_path, cls))
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))]
            if not imgs:
                errors.append(f"  ✗ Class rỗng ({split}/{cls})")
            else:
                print(f"  ✓ {split}/{cls}: {len(imgs)} ảnh")
    if errors:
        print("\n[ERROR] Dữ liệu chưa sẵn sàng:")
        for e in errors: print(e)
        print("\n[HINT]  Chạy prepare_faces.py trước.")
        exit(1)


# ─── Data Loaders ────────────────────────────────────────────────────────────

def get_loaders(data_dir: str = DATA_DIR, batch_size: int = BATCH_SIZE):
    weights    = MobileNet_V2_Weights.DEFAULT
    mean       = weights.meta["mean"]
    std        = weights.meta["std"]
    fill_color = tuple(int(m * 255) for m in mean)

    train_tfms = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(15, fill=fill_color),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
        transforms.RandomGrayscale(p=0.05),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])
    val_tfms = get_transform()

    train_ds = datasets.ImageFolder(os.path.join(data_dir, "train"), transform=train_tfms)
    val_ds   = datasets.ImageFolder(os.path.join(data_dir, "val"),   transform=val_tfms)

    num_workers = 0 if platform.system() == "Windows" else 2
    use_pin     = torch.cuda.is_available()

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=num_workers, pin_memory=use_pin)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False,
                              num_workers=num_workers, pin_memory=use_pin)

    return train_ds, val_ds, train_loader, val_loader


# ─── Train / Eval ────────────────────────────────────────────────────────────

def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: optim.Optimizer,
    use_cutmix: bool = USE_CUTMIX,
) -> tuple:
    model.train()
    enforce_frozen_bn(model)

    running_loss = running_correct = total = 0

    for images, labels in loader:
        images, labels = images.to(DEVICE), labels.to(DEVICE)
        optimizer.zero_grad()

        # [v14] Targeted Eye CutMix (use_targeted=True)
        if use_cutmix and np.random.rand() < CUTMIX_PROB:
            mixed_imgs, labels_a, labels_b, lam = cutmix_batch(
                images, labels, use_targeted=True
            )
            outputs = model(mixed_imgs)
            loss = lam * criterion(outputs, labels_a) + (1 - lam) * criterion(outputs, labels_b)
            preds = torch.argmax(outputs, dim=1)
            target_for_acc = labels_a if lam >= 0.5 else labels_b
        else:
            outputs = model(images)
            loss = criterion(outputs, labels)
            preds = torch.argmax(outputs, dim=1)
            target_for_acc = labels

        loss.backward()
        optimizer.step()

        running_loss    += loss.item() * images.size(0)
        running_correct += (preds == target_for_acc).sum().item()
        total           += labels.size(0)

    return running_loss / total, running_correct / total


@torch.inference_mode()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
) -> tuple:
    model.eval()
    running_loss = running_correct = total = 0
    all_preds, all_labels = [], []

    for images, labels in loader:
        images, labels = images.to(DEVICE), labels.to(DEVICE)
        outputs = model(images)
        loss    = criterion(outputs, labels)

        running_loss    += loss.item() * images.size(0)
        preds            = torch.argmax(outputs, dim=1)
        running_correct += (preds == labels).sum().item()
        total           += labels.size(0)
        all_preds.extend(preds.cpu().tolist())
        all_labels.extend(labels.cpu().tolist())

    avg_loss = running_loss / total
    avg_acc  = running_correct / total

    if _SKLEARN:
        prec, rec, f1, _ = precision_recall_fscore_support(
            all_labels, all_preds, average="macro", zero_division=0
        )
    else:
        prec = rec = f1 = float("nan")

    return avg_loss, avg_acc, prec, rec, f1


# ─── Main ────────────────────────────────────────────────────────────────────

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Train sleepiness model v17")
    p.add_argument("--epochs",     type=int,   default=EPOCHS)
    p.add_argument("--batch-size", type=int,   default=BATCH_SIZE)
    p.add_argument("--lr",         type=float, default=LR)
    p.add_argument("--backbone",   default="mobilenet_v2",
                   choices=["mobilenet_v2", "resnet18", "resnet50", "efficientnet_b0"])
    p.add_argument("--no-cutmix",  action="store_true")
    p.add_argument("--resume",     action="store_true",
                   help="Tiếp tục training từ checkpoint cũ nếu có")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    validate_data_dirs()
    train_ds, val_ds, train_loader, val_loader = get_loaders(batch_size=args.batch_size)
    class_names = train_ds.classes

    with open(CLASSES_PATH, "w", encoding="utf-8") as f:
        json.dump(class_names, f, ensure_ascii=False, indent=2)

    model     = build_model(len(class_names), training=True, backbone=args.backbone).to(DEVICE)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_p   = sum(p.numel() for p in model.parameters())
    print(f"[INFO] Tham số train được: {trainable:,} / {total_p:,} ({trainable/total_p:.1%})")

    targets        = train_ds.targets
    class_counts   = Counter(targets)
    total_samples  = len(targets)
    weights        = []
    for i in range(len(class_names)):
        if class_counts[i] == 0:
            weights.append(0.0)
        else:
            weights.append(total_samples / (len(class_names) * class_counts[i]))
    class_weights = torch.FloatTensor(weights).to(DEVICE)

    criterion = FocalLoss(alpha=class_weights, gamma=FOCAL_GAMMA)
    print(f"[INFO] FocalLoss gamma={FOCAL_GAMMA} | alpha={dict(zip(class_names, weights))}")
    print(f"[INFO] Targeted Eye CutMix={'BẬT' if USE_CUTMIX else 'TẮT'} "
          f"(prob={CUTMIX_PROB}, eye_frac={EYE_REGION_FRAC})")

    from utils_model import get_trainable_param_groups
    optimizer = optim.Adam(get_trainable_param_groups(model, args.backbone, args.lr))
    scheduler = ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=2, min_lr=1e-6)

    print(f"\nDevice : {DEVICE}")
    print(f"Classes: {class_names}")
    print(f"Train  : {len(train_ds)} ảnh | Val: {len(val_ds)} ảnh")
    print(f"Epochs : tối đa {EPOCHS} (patience={EARLY_STOP_PATIENCE})\n")
    print("-" * 80)

    best_val_loss = float("inf")
    no_improve    = 0

    def _fmt(m: float) -> str:
        return f"{m:.3f}" if (_SKLEARN and m is not None and not math.isnan(m)) else "NaN"

    start_epoch = 0
    if args.resume and os.path.exists(MODEL_PATH):
        try:
            ckpt_resume = torch.load(MODEL_PATH, map_location=DEVICE)
            # [v18 FIX] Thực sự nạp lại trọng số model — trước đây chỉ đọc epoch
            # mà bỏ qua model_state_dict → "resume" thực chất train lại từ đầu.
            if "model_state_dict" in ckpt_resume:
                model.load_state_dict(ckpt_resume["model_state_dict"])
                best_val_loss = float(ckpt_resume.get("best_val_loss", best_val_loss))
                print("[RESUME] Đã nạp lại trọng số model từ checkpoint.")
            else:
                print("[RESUME][WARN] Checkpoint thiếu 'model_state_dict' → train từ đầu.")
            start_epoch = int(ckpt_resume.get("epoch", 0))
            print(f"[RESUME] Bắt đầu từ epoch {start_epoch} (best_val_loss={best_val_loss:.4f})")
        except Exception as e:
            print(f"[RESUME][WARN] Không đọc được checkpoint: {e}")
    for epoch in range(start_epoch, args.epochs):
        t0 = time.time()
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, use_cutmix=USE_CUTMIX and not args.no_cutmix)
        val_loss, val_acc, prec, rec, f1 = evaluate(model, val_loader, criterion)
        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            no_improve    = 0
            tag = " ← best"
            temp_path = MODEL_PATH + ".tmp"
            torch.save({
                "model_state_dict": model.state_dict(),
                "class_names": class_names,
                "backbone": args.backbone,
                "epoch": epoch + 1,
                # [v19 FIX] Lưu best_val_loss để --resume so sánh đúng. Trước đây
                # resume đọc key này (mặc định inf) → luôn ghi đè checkpoint tốt
                # bằng checkpoint epoch đầu tệ hơn ngay lần lưu kế tiếp.
                "best_val_loss": best_val_loss,
            }, temp_path)
            os.replace(temp_path, MODEL_PATH)
        else:
            no_improve += 1
            tag = f" (no improve {no_improve}/{EARLY_STOP_PATIENCE})"

        elapsed = time.time() - t0
        print(
            f"Epoch {epoch+1:3d}/{args.epochs} | "
            f"loss {train_loss:.4f}/{val_loss:.4f} | "
            f"acc {train_acc:.3f}/{val_acc:.3f} | "
            f"P={_fmt(prec)} R={_fmt(rec)} F1={_fmt(f1)} | "
            f"{elapsed:.1f}s{tag}"
        )

        if no_improve >= EARLY_STOP_PATIENCE:
            print(f"\n[Early Stop] Val loss không cải thiện sau {EARLY_STOP_PATIENCE} epochs.")
            break

    print(f"\n✅ Xong. Best val loss = {best_val_loss:.4f} | Model: {MODEL_PATH}")


if __name__ == "__main__":
    main()
