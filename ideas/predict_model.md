Use XGBoost to build model that evaulate if a stock has a good growth potential.

Inputs:
1. one week of Stock daily prices  in daily_prices table
2. one week of technical indicators in technical_indicators table

Object function:
If the highest price of a stock in the week immediately after the input week is at least 5% higher than the highest price of the stock in the input week, then this stock is considered positive, otherwise it is negative. 

The XGBoost model is trained using existing historical data,  taking every week's data as input, the object funtion defined above as the output.
