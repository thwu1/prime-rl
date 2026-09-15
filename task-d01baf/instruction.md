A 2-layer attention-only transformer is defined at `/app/transformer.py`. Read the module docstring and code for the full architecture specification (dimensions, subspace layout, embedding construction, forward pass).

Construct explicit numerical weight matrices for each of the two attention heads so that, together, they implement an **induction head circuit** via the **K-composition** mechanism described in the transformer circuits literature:

- **Head 1** (layer 1) must attend to the **previous token** at every position. Its OV circuit must copy token-content information into the **virtual subspace** (dims 16-23) of the residual stream, enabling downstream composition.

- **Head 2** (layer 2) must implement **induction**: given a sequence `[..., A, B, ..., A]`, it should attend to position `B` — the token that immediately followed the previous occurrence of the current token `A`. It must accomplish this by reading the virtual subspace (written by Head 1) as keys and the content subspace as queries (K-composition). Its OV circuit must copy the attended token's content to the output for unembedding.

The architecture uses **sinusoidal positional encodings** (frequencies in `POS_FREQS`) and **orthogonal content embeddings**. The previous-token attention pattern requires exploiting the rotational structure of sinusoidal encodings. Attention patterns must be sharply peaked (not diffuse).

Save your weight matrices to `/app/circuit_weights.npz` with keys: `W_Q1`, `W_K1`, `W_V1`, `W_O1`, `W_Q2`, `W_K2`, `W_V2`, `W_O2`.