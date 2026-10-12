# One-command entry points. Data is downloaded from Binance's public API (no keys needed).
PY ?= python3

.PHONY: test data results charts parity backtest paper all

test:        ## unit tests (29)
	$(PY) -m unittest -v tests.test_core

data:        ## download hourly data 2021 -> now (needs requirements-research.txt)
	$(PY) -m research.download_pre
	$(PY) -m research.download_full

results:     ## regenerate results/backtest (tear sheet, equity, years, 14-day windows, crashes, sleeves)
	$(PY) -m research.make_results

charts:      ## regenerate docs/img/*.svg from results/
	$(PY) -m research.make_charts

parity:      ## prove live code == research code
	$(PY) -m research.parity_check

backtest:    ## event-driven backtest of the live code, out-of-sample, with 14-day windows
	$(PY) -m backtest.engine --windows

paper:       ## one dry-run decision cycle of the live bot (test key, no orders)
	$(PY) -m bot.main --mode paper --once

all: test data results charts parity
