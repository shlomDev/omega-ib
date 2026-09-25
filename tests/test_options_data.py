from omega_ib.data.options import FakeOptionsData, OptionChain, OptionQuote, is_liquid, iv_percentile, iv_rank


def _quote(strike=100, right="C", bid=1.0, ask=1.1, oi=200, delta=0.3):
    return OptionQuote(symbol="AAPL", expiry="20261218", strike=strike, right=right, bid=bid, ask=ask, open_interest=oi, delta=delta)


def test_option_quote_mid_and_spread_pct():
    q = _quote(bid=1.0, ask=1.2)
    assert round(q.mid, 4) == 1.1
    assert round(q.spread_pct, 4) == round(0.2 / 1.1, 4)


def test_option_quote_spread_pct_inf_when_no_mid():
    q = _quote(bid=0.0, ask=0.0)
    assert q.spread_pct == float("inf")


def test_is_liquid_true_and_false():
    liquid = _quote(bid=1.0, ask=1.05, oi=500)
    illiquid_spread = _quote(bid=1.0, ask=2.0, oi=500)
    illiquid_oi = _quote(bid=1.0, ask=1.05, oi=5)
    assert is_liquid(liquid) is True
    assert is_liquid(illiquid_spread) is False
    assert is_liquid(illiquid_oi) is False


def test_option_chain_expiries_by_expiry_find():
    q1 = _quote(strike=100, right="C")
    q2 = OptionQuote(symbol="AAPL", expiry="20270115", strike=100, right="C", bid=2.0, ask=2.2)
    chain = OptionChain(symbol="AAPL", underlying_price=100.0, quotes=[q1, q2])
    assert chain.expiries() == ["20261218", "20270115"]
    assert chain.by_expiry("20261218") == [q1]
    assert chain.find("20261218", 100, "C") is q1
    assert chain.find("20261218", 999, "C") is None


def test_option_chain_liquid_quotes():
    liquid = _quote(strike=100, oi=500)
    illiquid = _quote(strike=105, oi=1)
    chain = OptionChain(symbol="AAPL", underlying_price=100.0, quotes=[liquid, illiquid])
    assert chain.liquid_quotes() == [liquid]


def test_iv_rank_and_percentile():
    history = [0.2, 0.3, 0.4, 0.5, 0.6]
    assert iv_rank(0.6, history) == 100.0
    assert iv_rank(0.2, history) == 0.0
    assert round(iv_rank(0.4, history), 6) == 50.0
    assert iv_percentile(0.6, history) == 80.0  # 4 of 5 below 0.6


def test_iv_rank_percentile_empty_history():
    assert iv_rank(0.5, []) == 0.0
    assert iv_percentile(0.5, []) == 0.0


def test_fake_options_data_chain_and_expiry_filter():
    provider = FakeOptionsData()
    q1 = _quote(strike=100, right="C")
    q2 = OptionQuote(symbol="AAPL", expiry="20270115", strike=100, right="C", bid=2.0, ask=2.2)
    provider.set_chain("AAPL", OptionChain(symbol="AAPL", underlying_price=150.0, quotes=[q1, q2]))
    full = provider.get_chain("AAPL")
    assert len(full.quotes) == 2
    filtered = provider.get_chain("AAPL", expiry="20261218")
    assert filtered.quotes == [q1]
    assert filtered.underlying_price == 150.0


def test_fake_options_data_missing_symbol():
    provider = FakeOptionsData()
    chain = provider.get_chain("NOPE")
    assert chain.quotes == []


def test_fake_options_data_iv_history():
    provider = FakeOptionsData()
    provider.set_iv_history("AAPL", [0.2, 0.3, 0.4])
    assert provider.iv_history("AAPL") == [0.2, 0.3, 0.4]
    assert provider.iv_history("MSFT") == []
