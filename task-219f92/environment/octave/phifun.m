function y = phifun(z, k)
% PHIFUN  Evaluate phi-function phi_k(z).
%
%   y = phifun(z, k) computes phi_k(z) for k = 0, 1, 2, 3.
%
%   phi_0(z) = exp(z)
%   phi_{k+1}(z) = (phi_k(z) - 1/k!) / z
%
%   Uses Taylor series for small |z| to avoid catastrophic cancellation.
%   Derived from the EXPINT package (Berland, Skaflestad, Wright, ACM TOMS 2007).

if k < 0 || k > 3
    error('phifun: k must be 0, 1, 2, or 3');
end

y = zeros(size(z));
for idx = 1:numel(z)
    zi = z(idx);
    if abs(zi) < 0.5
        % Taylor series: phi_k(z) = sum_{n=0}^{inf} z^n / (n+k)!
        s = 0;
        term = 1 / factorial(k);
        for n = 0:40
            s = s + term;
            term = term * zi / (n + k + 1);
            if abs(term) < eps * max(abs(s), 1)
                break;
            end
        end
        y(idx) = s;
    else
        ez = exp(zi);
        if k == 0
            y(idx) = ez;
        elseif k == 1
            y(idx) = (ez - 1) / zi;
        elseif k == 2
            y(idx) = (ez - 1 - zi) / zi^2;
        elseif k == 3
            y(idx) = (ez - 1 - zi - zi^2/2) / zi^3;
        end
    end
end
end
