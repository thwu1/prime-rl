
"""
Medical image segmentation evaluation pipeline using MONAI.
Evaluates a 3D UNet on synthetic volumetric data and reports the Dice metric.
"""

import torch
import numpy as np
from monai.networks.nets import UNet
from monai.inferers import sliding_window_inference
from monai.metrics import DiceMetric
from monai.transforms import (
    Compose,
    EnsureChannelFirstd,
    NormalizeIntensityd,
    ScaleIntensityRanged,
    AsDiscrete,
)
from monai.data import decollate_batch


def create_synthetic_data(num_samples=2, spatial_size=(32, 32, 32), num_classes=3, seed=42):
    """Generate synthetic 3D medical image data with spherical class regions."""
    rng = np.random.RandomState(seed)
    data_list = []
    for i in range(num_samples):
        image = rng.uniform(0, 1000, size=spatial_size).astype(np.float32)
        label = np.zeros(spatial_size, dtype=np.int64)
        center = np.array(spatial_size) // 2
        for c in range(1, num_classes):
            radius = spatial_size[0] // (num_classes + 1) * c
            coords = np.ogrid[tuple(slice(0, s) for s in spatial_size)]
            dist_sq = sum((coord - ctr) ** 2 for coord, ctr in zip(coords, center))
            mask = dist_sq <= radius ** 2
            label[mask] = c
        data_list.append({"image": image, "label": label})
    return data_list


def get_transforms():
    """Get preprocessing transforms for the evaluation pipeline."""
    return Compose([
        EnsureChannelFirstd(keys=["image", "label"], channel_dim=0),
        NormalizeIntensityd(keys=["image"]),
        ScaleIntensityRanged(
            keys=["image"], a_min=0.0, a_max=1000.0,
            b_min=0.0, b_max=1.0, clip=True,
        ),
    ])


def create_model(num_classes=3):
    """Create a UNet model for segmentation."""
    return UNet(
        spatial_dims=2,
        in_channels=1,
        out_channels=num_classes,
        channels=(16, 32, 64, 128),
        strides=(2, 2, 2),
        num_res_units=2,
    )


def run_evaluation(num_classes=3):
    """Run the full evaluation pipeline. Returns mean Dice metric."""
    data_list = create_synthetic_data(num_classes=num_classes)
    transforms = get_transforms()
    model = create_model(num_classes=num_classes)
    model.eval()

    dice_metric = DiceMetric(include_background=False, reduction="mean")
    post_pred = AsDiscrete(argmax=True, to_onehot=num_classes)
    post_label = AsDiscrete(to_onehot=num_classes)

    with torch.no_grad():
        for data in data_list:
            data = transforms(data)
            image = data["image"].unsqueeze(0).float()
            label = data["label"].unsqueeze(0).long()

            output = sliding_window_inference(
                image, roi_size=(16, 16, 16), sw_batch_size=4,
                predictor=model, overlap=1.5,
            )

            output_list = decollate_batch(output)
            label_list = decollate_batch(label)
            output_post = [post_pred(o) for o in output_list]
            label_post = [post_label(l) for l in label_list]

            dice_metric(y_pred=torch.stack(output_post), y=torch.stack(label_post))

    metric = dice_metric.aggregate().item()
    dice_metric.reset()
    return metric


def train_and_evaluate(num_classes=3, num_epochs=5):
    """Train model briefly with FocalTverskyLoss and evaluate.

    Returns:
        Tuple of (losses_per_epoch, dice_score).
    """
    from losses import FocalTverskyLoss

    torch.manual_seed(42)
    train_data = create_synthetic_data(
        num_samples=2, spatial_size=(16, 16, 16),
        num_classes=num_classes, seed=0
    )
    transforms = get_transforms()
    model = create_model(num_classes=num_classes)

    criterion = FocalTverskyLoss(
        alpha=0.7, beta=0.3, gamma=0.75,
        softmax=True, to_onehot_y=True,
        include_background=False,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)

    # Training phase
    model.train()
    losses = []
    for epoch in range(num_epochs):
        epoch_loss = 0.0
        for data in train_data:
            data = transforms(data)
            image = data["image"].unsqueeze(0).float()
            label = data["label"].unsqueeze(0).long()

            optimizer.zero_grad()
            output = model(image)
            loss = criterion(output, label)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        losses.append(epoch_loss / len(train_data))

    # Evaluate on training data (direct forward, no sliding window)
    model.eval()
    dice_metric = DiceMetric(include_background=False, reduction="mean")
    post_pred = AsDiscrete(argmax=True, to_onehot=num_classes)
    post_label = AsDiscrete(to_onehot=num_classes)

    with torch.no_grad():
        for data in train_data:
            data = transforms(data)
            image = data["image"].unsqueeze(0).float()
            label = data["label"].unsqueeze(0).long()

            output = model(image)
            output_list = decollate_batch(output)
            label_list = decollate_batch(label)
            output_post = [post_pred(o) for o in output_list]
            label_post = [post_label(l) for l in label_list]

            dice_metric(y_pred=torch.stack(output_post), y=torch.stack(label_post))

    dice = dice_metric.aggregate().item()
    dice_metric.reset()
    return losses, dice


if __name__ == "__main__":
    result = run_evaluation()
    print(f"Mean Dice: {result:.6f}")
