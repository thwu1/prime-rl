# Double Pendulum Equations of Motion

The double pendulum is modeled with 15 parameters: masses (m1, m2), link lengths (l1, l2), centers of mass (r1, r2), inertias (I1, I2), motor inertia Ir, gear ratio gr, coulomb friction (cf1, cf2), viscous friction (b1, b2), and gravity g.

The generalized coordinates q = (q1, q2) are joint angles measured from the free hanging (downward) position. The state vector is x = (q1, q2, qdot1, qdot2). Torques applied by actuators are u = (u1, u2).

## Manipulator Equation

    M(q) * qddot = -C(q, qdot) * qdot + G(q) + B * u - F(qdot)

equivalently:

    qddot = M(q)^{-1} * (B * u - C(q, qdot) * qdot + G(q) - F(qdot))

## Mass Matrix M(q)

    M11 = I1 + I2 + m2*l1^2 + 2*m2*l1*r2*cos(q2) + gr^2*Ir + Ir
    M12 = I2 + m2*l1*r2*cos(q2) - gr*Ir
    M21 = M12
    M22 = I2 + gr^2*Ir

## Coriolis Matrix C(q, qdot)

Let h = m2*l1*r2*sin(q2), then:

    C11 = -2*h*qdot2
    C12 = -h*qdot2
    C21 = h*qdot1
    C22 = 0

## Gravity Vector G(q)

    G1 = -m1*g*r1*sin(q1) - m2*g*(l1*sin(q1) + r2*sin(q1 + q2))
    G2 = -m2*g*r2*sin(q1 + q2)

## Friction Vector F(qdot)

    F1 = b1*qdot1 + cf1*arctan(100*qdot1)
    F2 = b2*qdot2 + cf2*arctan(100*qdot2)

## Actuator Selection Matrix B

For the acrobot (only joint 2 actuated):

    B = [[0, 0],
         [0, 1]]

## Energy

Kinetic energy:

    Ekin = 0.5 * qdot^T * M(q) * qdot

Potential energy:

    Epot = -m1*g*r1*cos(q1) - m2*g*(l1*cos(q1) + r2*cos(q1 + q2))

Total energy:

    E = Ekin + Epot

## Forward Kinematics

End-effector (tip of link 2) position relative to the pivot:

    x_ee = l1*sin(q1) + l2*sin(q1 + q2)
    y_ee = -l1*cos(q1) - l2*cos(q1 + q2)

The height threshold for swing-up success is y_ee >= 0.45 m.
