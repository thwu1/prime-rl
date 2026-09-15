import torch
import torch.nn as nn


class TargetModel(nn.Module):
    """Simple feedforward network."""

    def __init__(self):
        super().__init__()
        self.embed = nn.Linear(127, 513, bias=False)
        self.fc1 = nn.Linear(513, 2048)
        self.fc2 = nn.Linear(2048, 512)
        self.classifier = nn.Linear(512, 10)

    def forward(self, x):
        x = self.embed(x)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        x = self.classifier(x)
        return x
