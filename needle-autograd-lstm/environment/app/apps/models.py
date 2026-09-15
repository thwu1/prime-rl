import sys
sys.path.append('/app')
import needle as ndl
import needle.nn as nn
import numpy as np


class LanguageModel(nn.Module):
    def __init__(self, embedding_size, output_size, hidden_size, num_layers=1,
                 seq_model='lstm', seq_len=40, device=None, dtype="float32"):
        """
        A language model consisting of an embedding layer, a sequence model
        (LSTM), and a linear output layer.

        Parameters:
            embedding_size: dimension of embedding vectors
            output_size: size of vocabulary (dictionary)
            hidden_size: number of features in the hidden state
            num_layers: number of LSTM layers
            seq_model: 'lstm' (only lstm is required)
            device: device to place parameters on
            dtype: data type
        """
        super(LanguageModel, self).__init__()
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION

    def forward(self, x, h=None):
        """
        Given a sequence of token indices (and optional hidden state), return
        next-word logits and the final hidden state.

        Args:
            x: (seq_len, batch_size) integer token indices
            h: hidden state for the sequence model (see LSTM.forward)
        Returns:
            (out, h)
            out: (seq_len * batch_size, output_size) logits
            h: final hidden state from the sequence model
        """
        ### BEGIN YOUR SOLUTION
        raise NotImplementedError()
        ### END YOUR SOLUTION
