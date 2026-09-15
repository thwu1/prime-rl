function mpc = network
%NETWORK  4-bus test system for security-constrained unit commitment
%   with locational marginal price decomposition.
%   Based on PJM 5-bus system structure with modified parameters.

%   MATPOWER Case Format : Version 2
mpc.version = '2';

%% system MVA base
mpc.baseMVA = 100;

%% bus data
%	bus_i	type	Pd	Qd	Gs	Bs	area	Vm	Va	baseKV	zone	Vmax	Vmin
mpc.bus = [
	1	3	0	0	0	0	1	1	0	230	1	1.1	0.9;
	2	1	0	0	0	0	1	1	0	230	1	1.1	0.9;
	3	1	0	0	0	0	1	1	0	230	1	1.1	0.9;
	4	1	0	0	0	0	1	1	0	230	1	1.1	0.9;
];

%% generator data
%	bus	Pg	Qg	Qmax	Qmin	Vg	mBase	status	Pmax	Pmin	Pc1	Pc2	Qc1min	Qc1max	Qc2min	Qc2max	ramp_agc	ramp_10	ramp_30	ramp_q	apf
mpc.gen = [
	1	250	0	100	-100	1	100	1	500	0	0	0	0	0	0	0	0	200	0	0	0;
	2	100	0	50	-50	1	100	1	250	0	0	0	0	0	0	0	0	120	0	0	0;
	3	80	0	50	-50	1	100	1	200	0	0	0	0	0	0	0	0	80	0	0	0;
	4	0	0	50	-50	1	100	1	150	0	0	0	0	0	0	0	0	60	0	0	0;
];

%% branch data
%	fbus	tbus	r	x	b	rateA	rateB	rateC	ratio	angle	status	angmin	angmax
mpc.branch = [
	1	2	0.005	0.05	0	180	180	180	0	0	1	-360	360;
	1	3	0.010	0.10	0	100	100	100	0	0	1	-360	360;
	2	3	0.008	0.08	0	0	0	0	0	0	1	-360	360;
	2	4	0.006	0.06	0	120	120	120	0	0	1	-360	360;
	3	4	0.012	0.12	0	0	0	0	0	0	1	-360	360;
];

%% generator cost data
%	model	startup	shutdown	n	c1	c0
%	model=2 (polynomial), n=2: cost(P) = c1*P + c0 per hour when committed
mpc.gencost = [
	2	1200	0	2	14	100;
	2	600	0	2	32	80;
	2	400	0	2	48	60;
	2	250	0	2	55	40;
];
