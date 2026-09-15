#!/usr/bin/env node
//
// Howell catalog view-factor calculator.
// Reads JSON from stdin (single object or array for batch).
// Each query: {"formula": "<id>", ...params}
// Writes JSON result(s) to stdout.

'use strict';

var pi = Math.PI;
var sqrt = Math.sqrt;
var log = Math.log;
var atan = Math.atan;
var pow = Math.pow;

function C11(p) {
    var eps = 1e-10;
    var c = p.c; if (c < eps) c = eps;
    var X = p.a / c, Y = p.b / c;
    var X2 = X * X, Y2 = Y * Y;
    var F = log(sqrt((1 + X2) * (1 + Y2) / (1 + X2 + Y2)));
    F += X * sqrt(1 + Y2) * atan(X / sqrt(1 + Y2));
    F += Y * sqrt(1 + X2) * atan(Y / sqrt(1 + X2));
    F -= X * atan(X);
    F -= Y * atan(Y);
    F *= 2 / (pi * X * Y);
    return {"F12": F};
}

function C14(p) {
    var eps = 1e-10;
    var l = p.l; if (l < eps) l = eps;
    var H = p.h / l, W = p.w / l;
    var H2 = H * H, W2 = W * W;
    var F = W * atan(1 / W) + H * atan(1 / H);
    F -= sqrt(H2 + W2) * atan(sqrt(1 / (H2 + W2)));
    var tmp = (1 + W2) * (1 + H2) / (1 + W2 + H2);
    tmp *= pow(W2 * (1 + W2 + H2) / ((1 + W2) * (W2 + H2)), W2);
    tmp *= pow(H2 * (1 + H2 + W2) / ((1 + H2) * (W2 + H2)), H2);
    F += log(tmp) / 4;
    F /= (W * pi);
    return {"F12": F};
}

function C40(p) {
    var R = p.r / p.a;
    var X = (2 * R * R + 1) / (R * R);
    return {"F12": 0.5 * (X - sqrt(X * X - 4))};
}

function C41(p) {
    var R1 = p.r1 / p.a;
    var R2 = p.r2 / p.a;
    var X = 1 + (1 + R2 * R2) / (R1 * R1);
    var R21 = R2 / R1;
    return {"F12": 0.5 * (X - sqrt(X * X - 4 * R21 * R21))};
}

function C79(p) {
    var eps = 1e-10;
    var r = p.r; if (r < eps) r = eps;
    var H = p.h / (2 * r);
    return {"F12": 2 * H * (sqrt(1 + H * H) - H)};
}

function C135(p) {
    var ratio = p.r1 / p.r2;
    return {"F12": 1.0, "F21": ratio * ratio, "F22": 1 - ratio * ratio};
}

var formulas = {
    'C-11': C11,
    'C-14': C14,
    'C-40': C40,
    'C-41': C41,
    'C-79': C79,
    'C-135': C135
};

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function(d) { input += d; });
process.stdin.on('end', function() {
    try {
        var data = JSON.parse(input);
        var batch = Array.isArray(data);
        var queries = batch ? data : [data];
        var results = queries.map(function(q) {
            var fn = formulas[q.formula];
            if (!fn) return {"error": "Unknown formula: " + q.formula};
            var params = {};
            Object.keys(q).forEach(function(k) {
                if (k !== 'formula') params[k] = q[k];
            });
            return fn(params);
        });
        process.stdout.write(JSON.stringify(batch ? results : results[0]) + '\n');
    } catch(e) {
        process.stderr.write('Error: ' + e.message + '\n');
        process.exit(1);
    }
});
