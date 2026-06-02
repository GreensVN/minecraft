"""
utils_model.py — Module dùng chung.

CHANGELOG v21:
    [FIX]      EWMAPredictor race condition: Di chuyển base.predict_probs() vào trong lock.
    [FIX]      Thay Lock bằng RLock để hỗ trợ recursive locking.
    [NEW]      ThreadSafeCLAHE: Thread-safe wrapper cho cv2.CLAHE.

CHANGELOG v16:
    [NEW]      TorchPredictor: Bọc PyTorch model với cùng interface OnnxPredictor.
               Cho phép EWMAPredictor hoạt động trên cả PyTorch path.
    [NEW]      _preprocess_face(): DRY tiền xử lý BGR → float32 tensor.
    [NEW]      EfficientNet-B0 và ResNet50 backbones.
    [NEW]      get_trainable_param_groups(): Optimizer param groups backbone-agnostic.
    [NEW]      get_normal_class_idx(): Tìm index class "bình thường".
    [NEW]      EWMAPredictor.predict_all_probs(): Vector EWMA đầy đủ.
    [FIX]      Python 3.8 compat: dict→Dict, list→List trong type hints.

CHANGELOG v14: OnnxPredictor multi-EP, EWMAPredictor, onnx.checker.check_model.
"""

import inspect
import json
import logging
import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
from PIL import Image
from torch import nn
from torchvision import models, transforms
from torchvision.models import MobileNet_V2_Weights

_WEIGHTS_DEFAULT = MobileNet_V2_Weights.DEFAULT
logger = logging.getLogger(__name__)


def get_default_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


DEVICE       = get_default_device()
MODEL_PATH   = "sleepiness_model.pth"
CLASSES_PATH = "class_names.json"

_NORMAL_CLASS_ALIASES = frozenset({
    "binh_thuong", "binh thuong", "normal", "awake", "alert",
    "tinh_tao", "tinh tao", "khong_buon_ngu",
})


# ─── [v21] Thread-Safe CLAHE Wrapper ─────────────────────────────────────────

class ThreadSafeCLAHE:
    """
    [v21 NEW] Thread-safe wrapper cho cv2.CLAHE.

    cv2.CLAHE không thread-safe khi được share giữa nhiều threads.
    Wrapper này sử dụng threading.Lock để đảm bảo chỉ một thread
    có thể gọi apply() tại một thời điểm.

    Alternative approach: Tạo per-thread CLAHE instance với threading.local,
    nhưng cách này đơn giản hơn và đủ cho use case hiện tại.
    """

    def __init__(self, clip_limit: float = 2.0, tile_grid_size: Tuple[int, int] = (8, 8)):
        """
        Initialize thread-safe CLAHE.

        Args:
            clip_limit: Contrast limiting threshold
            tile_grid_size: Size of grid for histogram equalization
        """
        self._clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
        self._lock = threading.Lock()
        self._clip_limit = clip_limit
        self._tile_grid_size = tile_grid_size

    def apply(self, img: np.ndarray) -> np.ndarray:
        """
        Apply CLAHE to image in thread-safe manner.

        Args:
            img: Input grayscale image (single channel)

        Returns:
            CLAHE-enhanced image
        """
        with self._lock:
            return self._clahe.apply(img)

    def reconfigure(self, clip_limit: float, tile_grid_size: Tuple[int, int]) -> None:
        """
        Reconfigure CLAHE parameters (thread-safe).

        Args:
            clip_limit: New contrast limiting threshold
            tile_grid_size: New grid size
        """
        with self._lock:
            self._clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
            self._clip_limit = clip_limit
            self._tile_grid_size = tile_grid_size

    def get_params(self) -> Dict[str, any]:
        """Get current CLAHE parameters."""
        with self._lock:
            return {
                'clip_limit': self._clip_limit,
                'tile_grid_size': self._tile_grid_size
            }


def get_normal_class_idx(class_names: List[str]) -> int:
    """[v16] Tìm index class 'bình thường' (VN/EN)."""
    for i, name in enumerate(class_names):
        if name.strip().lower() in _NORMAL_CLASS_ALIASES:
            return i
    logger.warning(f"[MODEL] Không tìm thấy class 'bình thường' trong {class_names}.")
    return 0


def enforce_frozen_bn(model: nn.Module) -> None:
    """Đóng băng running stats của BatchNorm không train."""
    for m in model.modules():
        if isinstance(m, (nn.BatchNorm2d, nn.BatchNorm1d, nn.SyncBatchNorm)):
            if not any(p.requires_grad for p in m.parameters()):
                m.eval()


def build_model(
    num_classes: int,
    training: bool = False,
    init_pretrained: bool = True,
    backbone: str = "mobilenet_v2",
) -> nn.Module:
    """[v16] Hỗ trợ: mobilenet_v2, resnet18, resnet50, efficientnet_b0."""
    if not isinstance(num_classes, int) or num_classes <= 0:
        raise ValueError(f"num_classes phải là số nguyên dương, nhận: {num_classes!r}")

    backbone_norm = str(backbone).strip().lower()

    if backbone_norm == "mobilenet_v2":
        weights = _WEIGHTS_DEFAULT if init_pretrained else None
        model   = models.mobilenet_v2(weights=weights)
        for p in model.parameters():
            p.requires_grad = False
        if training and hasattr(model, "features") and len(model.features) > 0:
            for p in model.features[-1].parameters():
                p.requires_grad = True
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, num_classes)

    elif backbone_norm == "resnet18":
        weights = models.ResNet18_Weights.DEFAULT if init_pretrained else None
        model   = models.resnet18(weights=weights)
        for p in model.parameters():
            p.requires_grad = False
        if training and hasattr(model, "layer4"):
            for p in model.layer4.parameters():
                p.requires_grad = True
        in_features = model.fc.in_features
        model.fc = nn.Linear(in_features, num_classes)

    elif backbone_norm == "resnet50":
        weights = models.ResNet50_Weights.DEFAULT if init_pretrained else None
        model   = models.resnet50(weights=weights)
        for p in model.parameters():
            p.requires_grad = False
        if training and hasattr(model, "layer4"):
            for p in model.layer4.parameters():
                p.requires_grad = True
        in_features = model.fc.in_features
        model.fc = nn.Linear(in_features, num_classes)

    elif backbone_norm == "efficientnet_b0":
        weights = models.EfficientNet_B0_Weights.DEFAULT if init_pretrained else None
        model   = models.efficientnet_b0(weights=weights)
        for p in model.parameters():
            p.requires_grad = False
        if training:
            for p in model.features[-1].parameters():
                p.requires_grad = True
        in_features = model.classifier[1].in_features
        model.classifier[1] = nn.Linear(in_features, num_classes)

    else:
        raise NotImplementedError(
            f"Backbone '{backbone_norm}' chưa hỗ trợ. "
            f"Hỗ trợ: 'mobilenet_v2', 'resnet18', 'resnet50', 'efficientnet_b0'."
        )

    return model


def get_trainable_param_groups(model: nn.Module, backbone: str, lr: float) -> List[dict]:
    """[v16] Param groups backbone-agnostic cho optimizer."""
    backbone_norm = str(backbone).strip().lower()

    if backbone_norm in ("mobilenet_v2", "efficientnet_b0"):
        head_params     = list(model.classifier[1].parameters())
        backbone_params = list(model.features[-1].parameters())
    elif backbone_norm in ("resnet18", "resnet50"):
        head_params     = list(model.fc.parameters())
        backbone_params = list(model.layer4.parameters())
    else:
        all_params = [p for p in model.parameters() if p.requires_grad]
        return [{"params": all_params, "lr": lr, "name": "all"}]

    head_p     = [p for p in head_params     if p.requires_grad]
    backbone_p = [p for p in backbone_params if p.requires_grad]

    groups = []
    if backbone_p:
        groups.append({"params": backbone_p, "lr": lr * 0.1, "name": "backbone_tail"})
    if head_p:
        groups.append({"params": head_p,     "lr": lr,       "name": "head"})

    if not groups:
        all_p = [p for p in model.parameters() if p.requires_grad]
        groups = [{"params": all_p, "lr": lr, "name": "all"}]

    return groups


def load_model(
    model_path: str = MODEL_PATH,
    classes_path: str = CLASSES_PATH,
    device: Optional[str] = None,
    backbone: Optional[str] = None,
) -> Tuple[nn.Module, List[str]]:
    target_device = device if device is not None else DEVICE

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Không tìm thấy model: '{model_path}'. Chạy: python train_sleepiness.py"
        )

    load_kwargs: dict = {"map_location": target_device}
    if "weights_only" in inspect.signature(torch.load).parameters:
        load_kwargs["weights_only"] = True
    else:
        logging.warning("[WARN] PyTorch < 1.13 — không có weights_only=True.")

    ckpt = torch.load(model_path, **load_kwargs)

    if "model_state_dict" not in ckpt:
        raise KeyError(f"Checkpoint thiếu 'model_state_dict'.")

    state_dict = ckpt["model_state_dict"]

    if backbone is not None:
        backbone_resolved = str(backbone).strip().lower()
    elif "backbone" in ckpt:
        backbone_resolved = str(ckpt["backbone"]).strip().lower()
    else:
        sd_keys = set(state_dict.keys())
        if any(k.startswith("features.") for k in sd_keys):
            backbone_resolved = "mobilenet_v2"
        elif any(k.startswith("layer") or k.startswith("fc.") for k in sd_keys):
            backbone_resolved = "resnet18"
        else:
            backbone_resolved = "mobilenet_v2"

    output_weight_keys = [
        k for k in state_dict.keys()
        if k.endswith(".weight") and ("classifier" in k or k.startswith("fc."))
    ]
    num_classes_from_weights = (
        state_dict[output_weight_keys[-1]].shape[0] if output_weight_keys else None
    )

    if "class_names" in ckpt:
        class_names = ckpt["class_names"]
    elif os.path.exists(classes_path):
        try:
            with open(classes_path, "r", encoding="utf-8") as f:
                class_names = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"File nhãn hỏng JSON: {e}") from e
    else:
        raise FileNotFoundError(f"Thiếu '{classes_path}'.")

    if num_classes_from_weights is not None and len(class_names) != num_classes_from_weights:
        raise ValueError(
            f"[load_model] Số nhãn không khớp số class của mạng. "
            f"Model checkpoint '{model_path}' có {num_classes_from_weights} class; "
            f"class_names ('{classes_path}') có {len(class_names)} nhãn ({class_names}). "
            f"Cách sửa: chạy lại train_sleepiness.py hoặc dùng đúng checkpoint."
        )

    model = build_model(len(class_names), training=False, init_pretrained=False,
                        backbone=backbone_resolved)
    model.load_state_dict(state_dict)
    model.to(target_device).eval()

    try:
        dummy = torch.zeros(1, 3, 224, 224, device=target_device)
        with torch.inference_mode():
            _ = model(dummy)
    except Exception as e:
        logging.warning(f"[WARN] Warm-up thất bại: {e}.")

    return model, class_names


def get_transform(
    img_size: int = 224,
    mean: Optional[List[float]] = None,
    std: Optional[List[float]] = None,
):
    if mean is not None and (not hasattr(mean, "__len__") or len(mean) != 3):
        raise ValueError(f"mean phải có 3 giá trị RGB, nhận: {mean!r}")
    if std is not None and (not hasattr(std, "__len__") or len(std) != 3):
        raise ValueError(f"std phải có 3 giá trị RGB, nhận: {std!r}")

    final_mean = mean or [0.485, 0.456, 0.406]
    final_std  = std  or [0.229, 0.224, 0.225]

    return transforms.Compose([
        transforms.Resize((img_size, img_size),
                          interpolation=transforms.InterpolationMode.BILINEAR),
        transforms.ToTensor(),
        transforms.Normalize(mean=final_mean, std=final_std),
    ])


def _preprocess_face(
    face_bgr: np.ndarray,
    img_size: int = 224,
    mean: Optional[np.ndarray] = None,
    std: Optional[np.ndarray] = None,
) -> np.ndarray:
    """[v16] BGR → float32 NCHW. Dùng chung bởi OnnxPredictor."""
    import cv2
    if mean is None:
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
    if std is None:
        std  = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
    face_rgb     = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
    face_resized = cv2.resize(face_rgb, (img_size, img_size),
                              interpolation=cv2.INTER_LINEAR)
    x = face_resized.transpose(2, 0, 1).astype(np.float32) / 255.0
    x = (x - mean) / std
    return np.expand_dims(x, 0)


def export_to_onnx(
    model: nn.Module,
    output_path: str,
    img_size: int = 224,
    opset_version: int = 17,
) -> str:
    model.eval()
    dummy_input = torch.zeros(1, 3, img_size, img_size)

    export_kwargs = dict(
        opset_version=opset_version,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes={"input": {0: "batch_size"}, "logits": {0: "batch_size"}},
        do_constant_folding=True,
    )
    # [v21] torch >= 2.9 defaults torch.onnx.export to the dynamo (torch.export)
    # backend. For this MobileNet/ResNet family that path then asks onnxscript's
    # version_converter to downconvert to opset 17 and crashes with
    # "No initializer or constant input to node found", spamming a traceback even
    # though a file is ultimately written. The legacy TorchScript exporter
    # (dynamo=False) handles opset_version + dynamic_axes exactly and cleanly.
    # Only pass the flag when this torch actually has it (≥ 2.5); older torch
    # would raise TypeError on an unknown kwarg.
    if "dynamo" in inspect.signature(torch.onnx.export).parameters:
        export_kwargs["dynamo"] = False

    temp_path = output_path + ".tmp"
    with torch.inference_mode():
        # The legacy exporter emits a DeprecationWarning; it's informational and
        # the produced model is validated below, so silence the noise.
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            torch.onnx.export(model, dummy_input, temp_path, **export_kwargs)

    try:
        import onnx
        model_onnx = onnx.load(temp_path)
        onnx.checker.check_model(model_onnx)
        logger.info("[ONNX] Xác thực: PASS")
    except ImportError:
        logger.warning("[ONNX] Không có gói 'onnx'. Bỏ qua xác thực.")
    except Exception as e:
        logger.error(f"[ONNX] Xác thực thất bại: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    os.replace(temp_path, output_path)
    size_mb = os.path.getsize(output_path) / (1024 ** 2)
    logger.info(f"[ONNX] Đã xuất: '{output_path}' ({size_mb:.1f} MB)")
    return output_path


def _build_onnx_providers() -> List[str]:
    """Thứ tự ưu tiên: CoreML → DirectML → CUDA → CPU."""
    try:
        import onnxruntime as ort
        available = set(ort.get_available_providers())
    except ImportError:
        return ["CPUExecutionProvider"]

    priority = [
        "CoreMLExecutionProvider",
        "DirectMLExecutionProvider",
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    selected = [p for p in priority if p in available]
    if "CPUExecutionProvider" not in selected:
        selected.append("CPUExecutionProvider")
    logger.info(f"[ONNX] Providers: {selected}")
    return selected


class OnnxPredictor:
    """[v16] Dùng _preprocess_face() chung. [v14] Multi-EP."""

    def __init__(self, onnx_path: str, class_names: List[str], img_size: int = 224):
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise ImportError("Cài: pip install onnxruntime") from e

        if not os.path.exists(onnx_path):
            raise FileNotFoundError(
                f"Không tìm thấy ONNX: '{onnx_path}'. Chạy: python export_onnx.py"
            )

        providers = _build_onnx_providers()
        self.session     = ort.InferenceSession(onnx_path, providers=providers)
        self.class_names = class_names
        self.img_size    = img_size
        self.input_name  = self.session.get_inputs()[0].name
        self._mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
        self._std  = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

        dummy = np.zeros((1, 3, img_size, img_size), dtype=np.float32)
        self.session.run(None, {self.input_name: dummy})

    def _run_inference(self, face_bgr: np.ndarray) -> np.ndarray:
        x      = _preprocess_face(face_bgr, self.img_size, self._mean, self._std)
        logits = self.session.run(None, {self.input_name: x})[0]
        exp_l  = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs  = (exp_l / exp_l.sum(axis=1, keepdims=True))[0]
        return probs.astype(np.float32)

    def predict(self, face_bgr: np.ndarray) -> Tuple[str, float]:
        probs = self._run_inference(face_bgr)
        idx   = int(np.argmax(probs))
        return self.class_names[idx], float(probs[idx])

    def predict_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        return self._run_inference(face_bgr)

    # [v17] Alias cho khớp interface với EWMAPredictor.predict_all_probs
    def predict_all_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        return self._run_inference(face_bgr)


class TorchPredictor:
    """
    [v16 NEW] Bọc PyTorch model với cùng interface OnnxPredictor.

    Tác dụng: Trước v16, PyTorch path dùng lambda → không có predict_probs() →
    EWMAPredictor không bọc được → PyTorch thiếu EWMA smoothing.
    v16: TorchPredictor cho phép EWMAPredictor hoạt động trên cả ONNX và PyTorch.
    """

    def __init__(
        self,
        model: nn.Module,
        class_names: List[str],
        img_size: int = 224,
        device: Optional[str] = None,
    ):
        self.model       = model
        self.class_names = class_names
        self.img_size    = img_size
        self.device      = device or DEVICE
        self._tfm        = get_transform(img_size)
        self.model.eval()

    def predict(self, face_bgr: np.ndarray) -> Tuple[str, float]:
        probs = self.predict_probs(face_bgr)
        idx   = int(np.argmax(probs))
        return self.class_names[idx], float(probs[idx])

    def predict_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        import cv2
        face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
        pil_img  = Image.fromarray(face_rgb)
        x        = self._tfm(pil_img).unsqueeze(0).to(self.device)
        with torch.inference_mode():
            logits = self.model(x)
            probs  = torch.softmax(logits, dim=1)[0]
        return probs.cpu().numpy().astype(np.float32)

    # [v17] Alias cho khớp interface với EWMAPredictor.predict_all_probs
    def predict_all_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        return self.predict_probs(face_bgr)


class EWMAPredictor:
    """
    [v21] EWMA filter trên Softmax với thread-safety improvements.
    [v16] Hoạt động trên cả OnnxPredictor và TorchPredictor.

    p_smooth[t] = alpha * p_raw[t] + (1 - alpha) * p_smooth[t-1]

    Thread-safety: Sử dụng RLock để bảo vệ toàn bộ prediction pipeline,
    bao gồm cả việc gọi base predictor để tránh race conditions.
    """

    def __init__(self, base_predictor, class_names: List[str], alpha: float = 0.5):
        if not (0.0 < float(alpha) <= 1.0):
            raise ValueError(f"alpha phải trong (0, 1], nhận: {alpha!r}")
        self.base        = base_predictor
        self.class_names = class_names
        self.alpha       = float(alpha)
        self._n_classes  = len(class_names)
        self._ewma: np.ndarray = np.full(
            self._n_classes, 1.0 / self._n_classes, dtype=np.float32
        )
        self._initialized = False
        # [v21] RLock thay vì Lock: cho phép recursive locking trong cùng thread
        # và bảo vệ toàn bộ prediction pipeline (bao gồm base.predict_probs)
        self._lock = threading.RLock()

    def predict(self, face_bgr: np.ndarray) -> Tuple[str, float]:
        # [v21] FIX: Di chuyển base.predict_probs() vào trong lock để tránh race
        with self._lock:
            raw_probs = self.base.predict_probs(face_bgr)
            self._update_ewma(raw_probs)
            idx = int(np.argmax(self._ewma))
            conf = float(self._ewma[idx])
            return self.class_names[idx], conf

    def predict_all_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        """[v16 NEW] Vector EWMA đầy đủ (num_classes,)."""
        # [v21] FIX: Di chuyển base.predict_probs() vào trong lock
        with self._lock:
            raw_probs = self.base.predict_probs(face_bgr)
            self._update_ewma(raw_probs)
            return self._ewma.copy()

    def _update_ewma(self, raw_probs: np.ndarray) -> None:
        """
        [v21] INTERNAL: Phải được gọi trong lock context.
        Cập nhật EWMA state với raw probabilities mới.
        """
        # [v19] Bảo vệ chống vector sai shape (vd model đổi số class giữa chừng).
        raw_probs = np.asarray(raw_probs, dtype=np.float32).reshape(-1)
        if raw_probs.shape[0] != self._n_classes:
            raise ValueError(
                f"raw_probs có {raw_probs.shape[0]} phần tử, kỳ vọng {self._n_classes}."
            )
        if not self._initialized:
            self._ewma        = raw_probs.copy()
            self._initialized = True
        else:
            self._ewma = self.alpha * raw_probs + (1.0 - self.alpha) * self._ewma

    def reset(self) -> None:
        """Reset EWMA state về uniform distribution."""
        with self._lock:
            self._ewma = np.full(
                self._n_classes, 1.0 / self._n_classes, dtype=np.float32
            )
            self._initialized = False
