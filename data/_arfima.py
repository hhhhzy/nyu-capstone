import numpy as np
from scipy.fft import fft, ifft
from scipy.stats import levy_stable, norm


def __ma_model(
    params,
    n_points,
    noise_std= 1,
    noise_alpha= 2,
):
    """Generate discrete series using MA process.
    Args:
        params: list[float]
            Coefficients used by the MA process:
                x[t] = epsi[t] + params[1]*epsi[t-1] + params[2]*epsi[t-2] + ...
            Order of the MA process is inferred from the length of this array.
        n_points: int
            Number of points to generate.
        noise_std: float, optional
            Scale of the generated noise (default: 1).
        noise_alpha: float, optional
            Parameter of the alpha-stable distribution (default: 2). Default
            value corresponds to Gaussian distribution.
    Returns:
        Discrete series (array of length n_points) generated by
        MA(len(params)) process
    """
    ma_order = len(params)
    if noise_alpha == 2:
        noise = norm.rvs(scale=noise_std, size=(n_points + ma_order))
    else:
        noise = levy_stable.rvs(
            noise_alpha, 0, scale=noise_std, size=(n_points + ma_order)
        )

    if ma_order == 0:
        return noise
    ma_coeffs = np.append([1], params)
    ma_series = np.zeros(n_points)
    for idx in range(ma_order, n_points + ma_order):
        take_idx = np.arange(idx, idx - ma_order - 1, -1).astype(int)
        ma_series[idx - ma_order] = np.dot(ma_coeffs, noise[take_idx])
    return ma_series[ma_order:]


def __arma_model(params, noise):
    """Generate discrete series using ARMA process.
    Args:
        params: list[float]
            Coefficients used by the AR process:
                x[t] = params[1]*x[t-1] + params[2]*x[t-2] + ... + epsi[t]
            Order of the AR process is inferred from the length of this array.
        noise: list[float]
            Values of the noise for each step. Length of the output array is
            automatically inferred from the length of this array. Note that
            noise needs not to be standard Gaussian noise (MA(0) process). It
            may be also generated by a higher order MA process.
    Returns:
        Discrete series (array of the same length as noise array) generated by
        the ARMA(len(params), ?) process.
    """
    ar_order = len(params)
    if ar_order == 0:
        return noise
    n_points = len(noise)
    arma_series = np.zeros(n_points + ar_order)
    for idx in np.arange(ar_order, len(arma_series)):
        take_idx = np.arange(idx - 1, idx - ar_order - 1, -1).astype(int)
        arma_series[idx] = np.dot(params, arma_series[take_idx]) + noise[idx - ar_order]
    return arma_series[ar_order:]


def __frac_diff(x, d):
    """Fast fractional difference algorithm (by Jensen & Nielsen (2014)).
    Args:
        x: list[float]
            Array of values to be differentiated.
        d: float
            Order of the differentiation. Recommend to use -0.5 < d < 0.5, but
            should work for almost any reasonable d.
    Returns:
        Fractionally differentiated series.
    """

    def next_pow2(n):
        # we assume that the input will always be n > 1,
        # so this brief calculation should be fine
        return (n - 1).bit_length()

    n_points = len(x)
    fft_len = 2 ** next_pow2(2 * n_points - 1)
    prod_ids = np.arange(1, n_points)
    frac_diff_coefs = np.append([1], np.cumprod((prod_ids - d - 1) / prod_ids))
    dx = ifft(fft(x, fft_len) * fft(frac_diff_coefs, fft_len))
    return np.real(dx[0:n_points])


def arfima(
    ar_params,
    d,
    ma_params,
    n_points,
    *,
    noise_std= 1,
    noise_alpha= 2,
    warmup= 0,
):
    """Generate series from ARFIMA process.
    Args:
        ar_params: list[float]
            Coefficients to be used by the AR process.
        d: float
            Differentiation order used by the ARFIMA process.
        ma_params: list[float]
            Coefficients to be used by the MA process.
        n_points: int
            Number of points to generate.
        noise_std: float, optional
            Scale of the generated noise (default: 1).
        noise_alpha: float, optional
            Parameter of the alpha-stable distribution (default: 2). Default
            value corresponds to Gaussian distribution.
        warmup: int, optional
            Number of points to generate as a warmup for the model
            (default: 0).
    Returns:
        Discrete series (array of length n_points) generated by the
        ARFIMA(len(ar_params), d, len(ma_params)) process.
    """
    ma_series = __ma_model(
        ma_params, n_points + warmup, noise_std=noise_std, noise_alpha=noise_alpha
    )
    frac_ma = __frac_diff(ma_series, -d)
    series = __arma_model(ar_params, frac_ma)
    return series[-n_points:]
