# Flow-Matching World Models for Robotic Manipulation: Methods

## 2.1 Rectified Flow Matching

We build on the rectified flow framework (Liu et al., 2022; Lipman et al., 2023)
which defines a straight-line interpolation between noise and data.  Inference
proceeds through a sequence of decreasing sigma values.  To concentrate more
capacity at high noise levels we apply a *shifted* schedule:

Given *N* denoising steps, let t_i = 1 - (i / N) for i = 0 ... N-1 (i.e.
uniformly spaced from 1 down to 1/N).  The shifted sigma for step *i* is

    sigma_i  =  s * t_i  /  ( 1 + (s - 1) * t_i )

where *s >= 1* is the flow-shift hyper-parameter.  When s = 1 the schedule
reduces to the linear schedule sigma = t.  Larger s pushes sigma values toward
1, spending more steps in the high-noise regime.

Denoising uses an Euler step along the predicted velocity field:

    x_{i+1}  =  x_i  +  v(x_i, sigma_i) * (sigma_{i+1} - sigma_i)

## 2.2 VAE Latent Geometry

The 3-D causal VAE compresses along temporal and spatial axes with different
strategies reflecting its architecture:

  * **Temporal.**  Because the encoder treats the first frame as an anchor,
    the temporal latent count is  ceil( F / f_t ) = (F - 1) // f_t + 1,
    where F is the frame count and f_t the temporal factor.

  * **Spatial.**  Standard strided convolutions give
    H_lat = H // f_s ,   W_lat = W // f_s
    with spatial factor f_s.

## 2.3 Reference-Frame Conditioning

In expand-timestep mode the model receives a per-latent binary mask **m** of
length T_lat:

  * m_j = 0  for reference (known) latent frames
  * m_j = 1  for generated (to-be-predicted) latent frames

The mask is expanded to pixel-frame space by repeating each entry f_t times and
truncating to the video length.  Blending is then

    x_blend  =  (1 - m) * x_cond  +  m * x_noise

so that reference positions retain the encoded condition while generated
positions start from noise.

## 2.4 Classifier-Free Guidance

Following Ho & Salimans (2022), the guided velocity is

    v_guided  =  v_uncond  +  w * ( v_cond  -  v_uncond )

with guidance scale w.  Setting w = 1 recovers the conditional prediction;
w > 1 amplifies the conditional signal.

## 2.5 Two-Stage Denoising

Wan 2.2 employs two transformer backbones, one specialised for high noise and
another for low noise.  The sigma schedule is split at index

    b  =  floor( N * r )

where r in [0, 1] is the boundary ratio.  Stage 1 comprises sigmas[0 : b] and
stage 2 comprises sigmas[b :].

## 2.6 Latent Normalisation

The VAE latent channels have heterogeneous statistics.  Before feeding latents
into the transformer they are normalised per channel:

    z_norm  =  ( z  -  mu_c )  /  sigma_c

with per-channel mean mu_c and standard deviation sigma_c.  Denormalisation
reverses this:

    z  =  z_norm * sigma_c  +  mu_c

## 2.7 Dual-Arm Action Representation

Each control timestep carries a 14-dimensional vector:

    [ left_arm (6-DOF),  left_gripper (1),
      right_arm (6-DOF), right_gripper (1) ]

Raw gripper readings in the range [g_low, g_high] are mapped to the normalised
range [0, 1] via linear interpolation with clipping to handle out-of-range
sensor noise:

    g_norm  =  clip( (g - g_low) / (g_high - g_low),  0,  1 )
