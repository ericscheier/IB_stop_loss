library(IBrokers)
tws <- twsConnect(port=7497)



test<-reqAccountUpdates(tws)
unrealized.pnl <- as.numeric(test[[1]][["UnrealizedPnL"]][["value"]])
net.liquidation <- as.numeric(test[[1]][["NetLiquidation"]][["value"]])

print(unrealized.pnl)
print(net.liquidation)

vol.threshold <- 0.0

daily.vol <- abs(unrealized.pnl / (net.liquidation - unrealized.pnl))

if (daily.vol >= vol.threshold){
  # Cancel all outstanding orders
  # open.positions <- twsPortfolioValue(test, zero.pos=FALSE)
  for(contract in test[[2]]){
    position.size <- contract[["portfolioValue"]][["position"]]
    if(position.size!=0){
      print(paste0("Closing Position: ",contract[["contract"]][["symbol"]]))
      buy.or.sell <- ifelse(position.size>0, "SELL", "BUY")
      close.order <- twsOrder(orderId=as.character(sample(1001:3001, 1)),#reqIds(tws)),
                              action = buy.or.sell,
                              totalQuantity = as.character(position.size),
                              orderType = "MKT")
      placeOrder(tws, Contract=as.twsContract(contract$contract), Order=close.order)
    }
  }
}

close(tws)
