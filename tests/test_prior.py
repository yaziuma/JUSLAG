import numpy as np
import pandas as pd

from juslag.config import JP_CYCLICAL, US_CYCLICAL
from juslag.prior import build_prior_eigenvectors, build_prior_exposure


def test_build_prior_eigenvectors_shape_and_no_nan() -> None:
    us = ["XLB", "XLE", "XLF"]
    jp = ["1617.T", "1618.T", "1619.T", "1620.T"]
    v0 = build_prior_eigenvectors(us, jp, US_CYCLICAL, JP_CYCLICAL)
    assert v0.shape == (len(us) + len(jp), 3)
    assert not np.isnan(v0).any()


def test_build_prior_exposure_shape_and_no_nan() -> None:
    us = ["XLB", "XLE", "XLF"]
    jp = ["1617.T", "1618.T", "1619.T", "1620.T"]
    cols = us + jp
    cc = pd.DataFrame(np.random.randn(200, len(cols)), columns=cols)
    v0 = build_prior_eigenvectors(us, jp, US_CYCLICAL, JP_CYCLICAL)
    c0 = build_prior_exposure(cc, v0)
    assert c0.shape == (len(cols), len(cols))
    assert not np.isnan(c0).any()
