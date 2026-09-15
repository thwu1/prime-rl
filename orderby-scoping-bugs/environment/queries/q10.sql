-- Report: fee inversion sorted ascending (most negative first)
SELECT account, -fee AS fee
FROM transactions
ORDER BY +fee;
