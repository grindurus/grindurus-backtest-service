Currently: 

POST /backtests - creates a backtest. It is then sent to compute provider.

Compute provider is defined in application/compute.py. 

Compute provider calls webhooks/backtest-completed which either transfers a job to success or to fail. 

Currently there is only a local compute provider, that waits for 3 seconds and returns default mock result. 

To create a new one you should define the one that calls whatever platform you'll use for backtests.
  
