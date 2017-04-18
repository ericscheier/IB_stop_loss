# -*- coding: utf-8 -*-
"""
Created on Fri Feb 24 12:55:46 2017

@author: eric
"""

from datetime import datetime

import swigibpy


class MyEWrapper(swigibpy.EWrapperVerbose):

    def historicalData(self, reqId, date, open, high, low, close, volume,
                       barCount, WAP, hasGaps):

      if date[:8] == 'finished':
          print("History request complete")
      else:
          date = datetime.strptime(date, "%Y%m%d").strftime("%d %b %Y")
          print(("History %s - Open: %s, High: %s, Low: %s, Close: "
                 "%s, Volume: %d") % (date, open, high, low, close, volume))

myWrapper = MyEWrapper()

tws = swigibpy.EPosixClientSocket(myWrapper, reconnect_auto=True)

tws.eConnect("", 7496, 42)

contract = swigibpy.Contract()
contract.exchange = "SMART"
contract.symbol = "GOOG"
contract.secType = "STK"
contract.currency = "USD"
today = datetime.today()

tws.reqHistoricalData(2, contract, today.strftime("%Y%m%d %H:%M:%S %Z"),
                      "1 W", "1 day", "TRADES", 0, 1, None)