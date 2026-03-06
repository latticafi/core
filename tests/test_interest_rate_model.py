import boa
import pytest


def test_initial_params(interest_rate_model):
    assert interest_rate_model.base_rate_bps() == 50
    assert interest_rate_model.optimal_utilization_bps() == 8000
    assert interest_rate_model.slope1_bps() == 400
    assert interest_rate_model.slope2_bps() == 7500


def test_get_rate_zero_utilization(interest_rate_model):
    assert interest_rate_model.get_rate(0) == 50


def test_get_rate_optimal_utilization(interest_rate_model):
    assert interest_rate_model.get_rate(8000) == 370


def test_get_rate_max_utilization(interest_rate_model):
    assert interest_rate_model.get_rate(10000) == 1870


def test_get_rate_50pct_utilization(interest_rate_model):
    assert interest_rate_model.get_rate(5000) == 250


def test_get_rate_90pct_above_kink(interest_rate_model):
    assert interest_rate_model.get_rate(9000) == 1120


def test_get_rate_over_max_reverts(interest_rate_model):
    with boa.reverts("utilization > MAX_BPS"):
        interest_rate_model.get_rate(10001)


def test_set_params(interest_rate_model, deployer):
    with boa.env.prank(deployer):
        interest_rate_model.set_params(100, 7000, 500, 8000)
    assert interest_rate_model.base_rate_bps() == 100
    assert interest_rate_model.optimal_utilization_bps() == 7000
    assert interest_rate_model.slope1_bps() == 500
    assert interest_rate_model.slope2_bps() == 8000
    assert interest_rate_model.get_rate(0) == 100


def test_set_params_non_owner_reverts(interest_rate_model, lender):
    with boa.env.prank(lender):
        with boa.reverts():
            interest_rate_model.set_params(100, 7000, 500, 8000)
