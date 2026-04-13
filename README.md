Currently: 

POST /backtests - creates a backtest. It is then sent to compute provider.

Compute provider is defined in application/compute.py. 

Currently there is only a local one, that waits for 3 seconds and returns default mock result. 

