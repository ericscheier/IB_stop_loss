"""
Copyright (C) 2016 Interactive Brokers LLC. All rights reserved.  This code is
subject to the terms and conditions of the IB API Non-Commercial License or the
 IB API Commercial License, as applicable.
"""

import sys
import argparse
import datetime
import collections
import inspect

import logging
import time
import os.path

from ibapi import wrapper
from ibapi.client import EClient
from ibapi.utils import iswrapper

# types
from ibapi.common import *
from ibapi.order_condition import *
from ibapi.contract import *
from ibapi.order import *
from ibapi.order_state import *
from ibapi.execution import Execution
from ibapi.execution import ExecutionFilter
from ibapi.commission_report import CommissionReport
from ibapi.scanner import ScannerSubscription
from ibapi.ticktype import *

from ibapi.account_summary_tags import *

from ContractSamples import ContractSamples
from OrderSamples import OrderSamples
from AvailableAlgoParams import AvailableAlgoParams
from ScannerSubscriptionSamples import ScannerSubscriptionSamples
from FaAllocationSamples import FaAllocationSamples


def SetupLogger():
    if not os.path.exists("log"):
        os.makedirs("log")

    time.strftime("pyibapi.%Y%m%d_%H%M%S.log")

    recfmt = '(%(threadName)s) %(asctime)s.%(msecs)03d %(levelname)s %(filename)s:%(lineno)d %(message)s'

    timefmt = '%y%m%d_%H:%M:%S'

    # logging.basicConfig( level=logging.DEBUG,
    #                    format=recfmt, datefmt=timefmt)
    logging.basicConfig(filename=time.strftime("log/pyibapi.%y%m%d_%H%M%S.log"),
                        filemode="w",
                        level=logging.INFO,
                        format=recfmt, datefmt=timefmt)
    logger = logging.getLogger()
    console = logging.StreamHandler()
    console.setLevel(logging.ERROR)
    logger.addHandler(console)


def printWhenExecuting(fn):
    def fn2(self):
        print("   doing", fn.__name__)
        fn(self)
        print("   done w/", fn.__name__)

    return fn2


class Activity(Object):
    def __init__(self, reqMsgId, ansMsgId, ansEndMsgId, reqId):
        self.reqMsdId = reqMsgId
        self.ansMsgId = ansMsgId
        self.ansEndMsgId = ansEndMsgId
        self.reqId = reqId


class RequestMgr(Object):
    def __init__(self):
        # I will keep this simple even if slower for now: only one list of
        # requests finding will be done by linear search
        self.requests = []

    def addReq(self, req):
        self.requests.append(req)

    def receivedMsg(self, msg):
        pass


# ! [socket_declare]
class TestClient(EClient):
    def __init__(self, wrapper):
        EClient.__init__(self, wrapper)
        # ! [socket_declare]

        # how many times a method is called to see test coverage
        self.clntMeth2callCount = collections.defaultdict(int)
        self.clntMeth2reqIdIdx = collections.defaultdict(lambda: -1)
        self.reqId2nReq = collections.defaultdict(int)
        self.setupDetectReqId()

    def countReqId(self, methName, fn):
        def countReqId_(*args, **kwargs):
            self.clntMeth2callCount[methName] += 1
            idx = self.clntMeth2reqIdIdx[methName]
            if idx >= 0:
                sign = -1 if 'cancel' in methName else 1
                self.reqId2nReq[sign * args[idx]] += 1
            return fn(*args, **kwargs)

        return countReqId_

    def setupDetectReqId(self):

        methods = inspect.getmembers(EClient, inspect.isfunction)
        for (methName, meth) in methods:
            if methName != "send_msg":
                # don't screw up the nice automated logging in the send_msg()
                self.clntMeth2callCount[methName] = 0
                # logging.debug("meth %s", name)
                sig = inspect.signature(meth)
                for (idx, pnameNparam) in enumerate(sig.parameters.items()):
                    (paramName, param) = pnameNparam
                    if paramName == "reqId":
                        self.clntMeth2reqIdIdx[methName] = idx

                setattr(TestClient, methName, self.countReqId(methName, meth))

                # print("TestClient.clntMeth2reqIdIdx", self.clntMeth2reqIdIdx)


# ! [ewrapperimpl]
class TestWrapper(wrapper.EWrapper):
    # ! [ewrapperimpl]
    def __init__(self):
        wrapper.EWrapper.__init__(self)

        self.wrapMeth2callCount = collections.defaultdict(int)
        self.wrapMeth2reqIdIdx = collections.defaultdict(lambda: -1)
        self.reqId2nAns = collections.defaultdict(int)
        self.setupDetectWrapperReqId()

    # TODO: see how to factor this out !!

    def countWrapReqId(self, methName, fn):
        def countWrapReqId_(*args, **kwargs):
            self.wrapMeth2callCount[methName] += 1
            idx = self.wrapMeth2reqIdIdx[methName]
            if idx >= 0:
                self.reqId2nAns[args[idx]] += 1
            return fn(*args, **kwargs)

        return countWrapReqId_

    def setupDetectWrapperReqId(self):

        methods = inspect.getmembers(wrapper.EWrapper, inspect.isfunction)
        for (methName, meth) in methods:
            self.wrapMeth2callCount[methName] = 0
            # logging.debug("meth %s", name)
            sig = inspect.signature(meth)
            for (idx, pnameNparam) in enumerate(sig.parameters.items()):
                (paramName, param) = pnameNparam
                # we want to count the errors as 'error' not 'answer'
                if 'error' not in methName and paramName == "reqId":
                    self.wrapMeth2reqIdIdx[methName] = idx

            setattr(TestWrapper, methName, self.countWrapReqId(methName, meth))

            # print("TestClient.wrapMeth2reqIdIdx", self.wrapMeth2reqIdIdx)


# this is here for documentation generation
"""
#! [ereader]
        #this code is in Client::connect() so it's automatically done, no need
        # for user to do it
        self.reader = reader.EReader(self.conn, self.msg_queue)
        self.reader.start()   # start thread

#! [ereader]
"""


# ! [socket_init]
class TestApp(TestWrapper, TestClient):
    def __init__(self):
        TestWrapper.__init__(self)
        TestClient.__init__(self, wrapper=self)
        # ! [socket_init]
        self.nKeybInt = 0
        self.started = False
        self.nextValidOrderId = None
        self.permId2ord = {}
        self.reqId2nErr = collections.defaultdict(int)
        self.globalCancelOnly = False

    def dumpTestCoverageSituation(self):
        for clntMeth in sorted(self.clntMeth2callCount.keys()):
            logging.debug("ClntMeth: %-30s %6d" % (clntMeth,
                                                   self.clntMeth2callCount[clntMeth]))

        for wrapMeth in sorted(self.wrapMeth2callCount.keys()):
            logging.debug("WrapMeth: %-30s %6d" % (wrapMeth,
                                                   self.wrapMeth2callCount[wrapMeth]))

    def dumpReqAnsErrSituation(self):
        logging.debug("%s\t%s\t%s\t%s" % ("ReqId", "#Req", "#Ans", "#Err"))
        for reqId in sorted(self.reqId2nReq.keys()):
            nReq = self.reqId2nReq.get(reqId, 0)
            nAns = self.reqId2nAns.get(reqId, 0)
            nErr = self.reqId2nErr.get(reqId, 0)
            logging.debug("%d\t%d\t%s\t%d" % (reqId, nReq, nAns, nErr))

    @iswrapper
    # ! [connectack]
    def connectAck(self):
        if self.async:
            self.startApi()

    # ! [connectack]

    @iswrapper
    # ! [nextvalidid]
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)

        logging.debug("setting nextValidOrderId: %d", orderId)
        self.nextValidOrderId = orderId
        # ! [nextvalidid]

        # we can start now
        self.start()

    def start(self):
        if self.started:
            return

        self.started = True

        print("Executing account operations requests")
        self.accountOperations_req()
        print("Executing requests ... finished")

    def keyboardInterrupt(self):
        self.nKeybInt += 1
        if self.nKeybInt == 1:
            self.stop()
        else:
            print("Finishing test")
            self.done = True

    def stop(self):
        print("Executing cancels")
        self.accountOperations_cancel()
        print("Executing cancels ... finished")

    def nextOrderId(self):
        oid = self.nextValidOrderId
        self.nextValidOrderId += 1
        return oid

    @iswrapper
    # ! [error]
    def error(self, reqId: TickerId, errorCode: int, errorString: str):
        super().error(reqId, errorCode, errorString)
        print("Error. Id: ", reqId, " Code: ", errorCode, " Msg: ", errorString)

    # ! [error] self.reqId2nErr[reqId] += 1


    @iswrapper
    def winError(self, text: str, lastError: int):
        super().winError(text, lastError)

    @iswrapper
    # ! [openorder]
    def openOrder(self, orderId: OrderId, contract: Contract, order: Order,
                  orderState: OrderState):
        super().openOrder(orderId, contract, order, orderState)
        print("OpenOrder. ID:", orderId, contract.symbol, contract.secType,
              "@", contract.exchange, ":", order.action, order.orderType,
              order.totalQuantity, orderState.status)
        # ! [openorder]

        order.contract = contract
        self.permId2ord[order.permId] = order

    @iswrapper
    # ! [openorderend]
    def openOrderEnd(self):
        super().openOrderEnd()
        print("OpenOrderEnd")
        # ! [openorderend]

        logging.debug("Received %d openOrders", len(self.permId2ord))

    @iswrapper
    # ! [orderstatus]
    def orderStatus(self, orderId: OrderId, status: str, filled: float,
                    remaining: float, avgFillPrice: float, permId: int,
                    parentId: int, lastFillPrice: float, clientId: int,
                    whyHeld: str):
        super().orderStatus(orderId, status, filled, remaining,
                            avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld)
        print("OrderStatus. Id:", orderId, "Status:", status, "Filled:", filled,
              "Remaining:", remaining, "AvgFillPrice:", avgFillPrice,
              "PermId:", permId, "ParentId:", parentId, "LastFillPrice:",
              lastFillPrice, "ClientId:", clientId, "WhyHeld:", whyHeld)

    # ! [orderstatus]


    @printWhenExecuting
    def accountOperations_req(self):
        # Requesting managed accounts***/
        # ! [reqmanagedaccts]
        # self.reqManagedAccts()
        # ! [reqmanagedaccts]
        # Requesting accounts' summary ***/


        # ! [reqaaccountsummary]
        # self.reqAccountSummary(9001, "All", AccountSummaryTags.AllTags)
        # ! [reqaaccountsummary]

        # ! [reqaaccountsummaryledger]
        # self.reqAccountSummary(9002, "All", "$LEDGER")
        # ! [reqaaccountsummaryledger]

        # ! [reqaaccountsummaryledgercurrency]
        # self.reqAccountSummary(9003, "All", "$LEDGER:EUR")
        # ! [reqaaccountsummaryledgercurrency]

        # ! [reqaaccountsummaryledgerall]
        # self.reqAccountSummary(9004, "All", "$LEDGER:ALL")
        # ! [reqaaccountsummaryledgerall]

        # Subscribing to an account's information. Only one at a time!
        # ! [reqaaccountupdates]
        self.reqAccountUpdates(True, self.account)
        # ! [reqaaccountupdates]

        # ! [reqaaccountupdatesmulti]
        # self.reqAccountUpdatesMulti(9005, self.account, "", True)
        # ! [reqaaccountupdatesmulti]

        # Requesting all accounts' positions.
        # ! [reqpositions]
        # self.reqPositions()
        # ! [reqpositions]

        # ! [reqpositionsmulti]
        # self.reqPositionsMulti(9006, self.account, "")
        # ! [reqpositionsmulti]

        # ! [reqfamilycodes]
        # self.reqFamilyCodes()
        # ! [reqfamilycodes]

    @printWhenExecuting
    def accountOperations_cancel(self):
        # ! [cancelaaccountsummary]
        self.cancelAccountSummary(9001)
        self.cancelAccountSummary(9002)
        self.cancelAccountSummary(9003)
        self.cancelAccountSummary(9004)
        # ! [cancelaaccountsummary]

        # ! [cancelaaccountupdates]
        self.reqAccountUpdates(False, self.account)
        # ! [cancelaaccountupdates]

        # ! [cancelaaccountupdatesmulti]
        self.cancelAccountUpdatesMulti(9005)
        # ! [cancelaaccountupdatesmulti]

        # ! [cancelpositions]
        self.cancelPositions()
        # ! [cancelpositions]

        # ! [cancelpositionsmulti]
        self.cancelPositionsMulti(9006)
        # ! [cancelpositionsmulti]

    @iswrapper
    # ! [managedaccounts]
    def managedAccounts(self, accountsList: str):
        super().managedAccounts(accountsList)
        print("Account list: ", accountsList)
        # ! [managedaccounts]

        self.account = accountsList.split(",")[0]

    @iswrapper
    # ! [accountsummary]
    def accountSummary(self, reqId: int, account: str, tag: str, value: str,
                       currency: str):
        super().accountSummary(reqId, account, tag, value, currency)
        print("Acct Summary. ReqId:", reqId, "Acct:", account,
              "Tag: ", tag, "Value:", value, "Currency:", currency)

    # ! [accountsummary]


    @iswrapper
    # ! [accountsummaryend]
    def accountSummaryEnd(self, reqId: int):
        super().accountSummaryEnd(reqId)
        print("AccountSummaryEnd. Req Id: ", reqId)

    # ! [accountsummaryend]


    @iswrapper
    # ! [updateaccountvalue]
    def updateAccountValue(self, key: str, val: str, currency: str,
                           accountName: str):
        super().updateAccountValue(key, val, currency, accountName)
        print("UpdateAccountValue. Key:", key, "Value:", val,
              "Currency:", currency, "AccountName:", accountName)

    # ! [updateaccountvalue]


    @iswrapper
    # ! [updateportfolio]
    def updatePortfolio(self, contract: Contract, position: float,
                        marketPrice: float, marketValue: float,
                        averageCost: float, unrealizedPNL: float,
                        realizedPNL: float, accountName: str):
        super().updatePortfolio(contract, position, marketPrice, marketValue,
                                averageCost, unrealizedPNL, realizedPNL, accountName)
        print("UpdatePortfolio.", contract.symbol, "", contract.secType, "@",
              contract.exchange, "Position:", position, "MarketPrice:", marketPrice,
              "MarketValue:", marketValue, "AverageCost:", averageCost,
              "UnrealizedPNL:", unrealizedPNL, "RealizedPNL:", realizedPNL,
              "AccountName:", accountName)

    # ! [updateportfolio]


    @iswrapper
    # ! [updateaccounttime]
    def updateAccountTime(self, timeStamp: str):
        super().updateAccountTime(timeStamp)
        print("UpdateAccountTime. Time:", timeStamp)

    # ! [updateaccounttime]


    @iswrapper
    # ! [accountdownloadend]
    def accountDownloadEnd(self, accountName: str):
        super().accountDownloadEnd(accountName)
        print("Account download finished:", accountName)

    # ! [accountdownloadend]


    @iswrapper
    # ! [position]
    def position(self, account: str, contract: Contract, position: float,
                 avgCost: float):
        super().position(account, contract, position, avgCost)
        print("Position.", account, "Symbol:", contract.symbol, "SecType:",
              contract.secType, "Currency:", contract.currency,
              "Position:", position, "Avg cost:", avgCost)

    # ! [position]


    @iswrapper
    # ! [positionend]
    def positionEnd(self):
        super().positionEnd()
        print("PositionEnd")

    # ! [positionend]


    @iswrapper
    # ! [positionmulti]
    def positionMulti(self, reqId: int, account: str, modelCode: str,
                      contract: Contract, pos: float, avgCost: float):
        super().positionMulti(reqId, account, modelCode, contract, pos, avgCost)
        print("Position Multi. Request:", reqId, "Account:", account,
              "ModelCode:", modelCode, "Symbol:", contract.symbol, "SecType:",
              contract.secType, "Currency:", contract.currency, ",Position:",
              pos, "AvgCost:", avgCost)

    # ! [positionmulti]


    @iswrapper
    # ! [positionmultiend]
    def positionMultiEnd(self, reqId: int):
        super().positionMultiEnd(reqId)
        print("Position Multi End. Request:", reqId)

    # ! [positionmultiend]


    @iswrapper
    # ! [accountupdatemulti]
    def accountUpdateMulti(self, reqId: int, account: str, modelCode: str,
                           key: str, value: str, currency: str):
        super().accountUpdateMulti(reqId, account, modelCode, key, value,
                                   currency)
        print("Account Update Multi. Request:", reqId, "Account:", account,
              "ModelCode:", modelCode, "Key:", key, "Value:", value,
              "Currency:", currency)

    # ! [accountupdatemulti]


    @iswrapper
    # ! [accountupdatemultiend]
    def accountUpdateMultiEnd(self, reqId: int):
        super().accountUpdateMultiEnd(reqId)
        print("Account Update Multi End. Request:", reqId)

    # ! [accountupdatemultiend]


    @iswrapper
    # ! [familyCodes]
    def familyCodes(self, familyCodes: ListOfFamilyCode):
        super().familyCodes(familyCodes)
        print("Family Codes:")
        for familyCode in familyCodes:
            print("Account ID: %s, Family Code Str: %s" % (
                familyCode.accountID, familyCode.familyCodeStr))

    # ! [familyCodes]


    @iswrapper
    # ! [marketdatatype]
    def marketDataType(self, reqId: TickerId, marketDataType: int):
        super().marketDataType(reqId, marketDataType)
        print("MarketDataType. ", reqId, "Type:", marketDataType)

    # ! [marketdatatype]

    @iswrapper
    # ! [tickprice]
    def tickPrice(self, reqId: TickerId, tickType: TickType, price: float,
                  attrib: TickAttrib):
        super().tickPrice(reqId, tickType, price, attrib)
        print("Tick Price. Ticker Id:", reqId, "tickType:", tickType, "Price:",
              price, "CanAutoExecute:", attrib.canAutoExecute,
              "PastLimit", attrib.pastLimit)

    # ! [tickprice]


    @iswrapper
    # ! [ticksize]
    def tickSize(self, reqId: TickerId, tickType: TickType, size: int):
        super().tickSize(reqId, tickType, size)
        print("Tick Size. Ticker Id:", reqId, "tickType:", tickType, "Size:", size)

    # ! [ticksize]


    @iswrapper
    # ! [tickgeneric]
    def tickGeneric(self, reqId: TickerId, tickType: TickType, value: float):
        super().tickGeneric(reqId, tickType, value)
        print("Tick Generic. Ticker Id:", reqId, "tickType:", tickType, "Value:", value)

    # ! [tickgeneric]


    @iswrapper
    # ! [tickstring]
    def tickString(self, reqId: TickerId, tickType: TickType, value: str):
        super().tickString(reqId, tickType, value)
        print("Tick string. Ticker Id:", reqId, "Type:", tickType, "Value:", value)

    # ! [tickstring]


    @iswrapper
    # ! [ticksnapshotend]
    def tickSnapshotEnd(self, reqId: int):
        super().tickSnapshotEnd(reqId)
        print("TickSnapshotEnd:", reqId)

    # ! [ticksnapshotend]


    @iswrapper
    # ! [updatemktdepth]
    def updateMktDepth(self, reqId: TickerId, position: int, operation: int,
                       side: int, price: float, size: int):
        super().updateMktDepth(reqId, position, operation, side, price, size)
        print("UpdateMarketDepth. ", reqId, "Position:", position, "Operation:",
              operation, "Side:", side, "Price:", price, "Size", size)

    # ! [updatemktdepth]


    @iswrapper
    # ! [updatemktdepthl2]
    def updateMktDepthL2(self, reqId: TickerId, position: int, marketMaker: str,
                         operation: int, side: int, price: float, size: int):
        super().updateMktDepthL2(reqId, position, marketMaker, operation, side,
                                 price, size)
        print("UpdateMarketDepthL2. ", reqId, "Position:", position, "Operation:",
              operation, "Side:", side, "Price:", price, "Size", size)

    # ! [updatemktdepthl2]



    @iswrapper
    # ! [realtimebar]
    def realtimeBar(self, reqId: TickerId, time: int, open: float, high: float,
                    low: float, close: float, volume: int, wap: float,
                    count: int):
        super().realtimeBar(reqId, time, open, high, low, close, volume, wap, count)
        print("RealTimeBars. ", reqId, "Time:", time, "Open:", open,
              "High:", high, "Low:", low, "Close:", close, "Volume:", volume,
              "Count:", count, "WAP:", wap)

    # ! [realtimebar]


    @iswrapper
    # ! [headTimestamp]
    def headTimestamp(self, reqId:int, headTimestamp:str):
        print("HeadTimestamp: ", reqId, " ", headTimestamp)
    # ! [headTimestamp]

    @iswrapper
    # ! [histogramData]
    def histogramData(self, reqId:int, items:HistogramData):
        print("HistogramData: ", reqId, " ", items)
    # ! [histogramData]

    @iswrapper
    # ! [historicaldata]
    def historicalData(self, reqId: TickerId, date: str, open: float, high: float,
                       low: float, close: float, volume: int, barCount: int,
                       WAP: float, hasGaps: int):
        super().historicalData(reqId, date, open, high, low, close, volume,
                               barCount, WAP, hasGaps)
        print("HistoricalData. ", reqId, " Date:", date, "Open:", open,
              "High:", high, "Low:", low, "Close:", close, "Volume:", volume,
              "Count:", barCount, "WAP:", WAP, "HasGaps:", hasGaps)
    # ! [historicaldata]

    @iswrapper
    # ! [historicaldataend]
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        print("HistoricalDataEnd ", reqId, "from", start, "to", end)

    # ! [historicaldataend]


    @iswrapper
    # ! [securityDefinitionOptionParameter]
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str,
                                          underlyingConId: int, tradingClass: str, multiplier: str,
                                          expirations: SetOfString, strikes: SetOfFloat):
        super().securityDefinitionOptionParameter(reqId, exchange,
                                                  underlyingConId, tradingClass, multiplier, expirations, strikes)
        print("Security Definition Option Parameter. ReqId:%d Exchange:%s "
              "Underlying conId: %d TradingClass:%s Multiplier:%s Exp:%s Strikes:%s",
              reqId, exchange, underlyingConId, tradingClass, multiplier,
              ",".join(expirations), ",".join(str(strikes)))

    # ! [securityDefinitionOptionParameter]


    @iswrapper
    # ! [securityDefinitionOptionParameterEnd]
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        super().securityDefinitionOptionParameterEnd(reqId)
        print("Security Definition Option Parameter End. Request: ", reqId)

    # ! [securityDefinitionOptionParameterEnd]


    @iswrapper
    # ! [tickoptioncomputation]
    def tickOptionComputation(self, reqId: TickerId, tickType: TickType,
                              impliedVol: float, delta: float, optPrice: float, pvDividend: float,
                              gamma: float, vega: float, theta: float, undPrice: float):
        super().tickOptionComputation(reqId, tickType, impliedVol, delta,
                                      optPrice, pvDividend, gamma, vega, theta, undPrice)
        print("TickOptionComputation. TickerId:", reqId, "tickType:", tickType,
              "ImpliedVolatility:", impliedVol, "Delta:", delta, "OptionPrice:",
              optPrice, "pvDividend:", pvDividend, "Gamma: ", gamma, "Vega:", vega,
              "Theta:", theta, "UnderlyingPrice:", undPrice)

    # ! [tickoptioncomputation]


    @iswrapper
    #! [tickNews]
    def tickNews(self, tickerId: int, timeStamp: int, providerCode: str, articleId: str, headline: str, extraData: str):
        print("tickNews: ", tickerId, ", timeStamp: ", timeStamp, ", providerCode: ", providerCode, ", articleId: ",
              articleId, ", headline: ", headline, "extraData: ", extraData)
    #! [tickNews]

    @iswrapper
    #! [historicalNews]
    def historicalNews(self, reqId: int, time: str, providerCode: str, articleId: str, headline: str):
        print("historicalNews: ", reqId, ", time: ", time, ", providerCode: ", providerCode, ", articleId: ",
              articleId, ", headline: ", headline)
    #! [historicalNews]

    @iswrapper
    #! [historicalNewsEnd]
    def historicalNewsEnd(self, reqId:int, hasMore:bool):
        print("historicalNewsEnd: ", reqId, ", hasMore: ", hasMore)
    #! [historicalNewsEnd]

    @iswrapper
    #! [newsProviders]
    def newsProviders(self, newsProviders: ListOfNewsProviders):
        print("newsProviders: ")
        for provider in newsProviders:
            print(provider)
    #! [newsProviders]

    @iswrapper
    #! [newsArticle]
    def newsArticle(self, reqId: int, articleType: int, articleText: str):
        print("newsArticle: ", reqId, ", articleType: ", articleType, ", articleText: ", articleText)
    #! [newsArticle]

    @iswrapper
    # ! [contractdetails]
    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        super().contractDetails(reqId, contractDetails)
        print("ContractDetails. ReqId:", reqId, contractDetails.summary.symbol,
              contractDetails.summary.secType, "ConId:", contractDetails.summary.conId,
              "@", contractDetails.summary.exchange)

    # ! [contractdetails]


    @iswrapper
    # ! [bondcontractdetails]
    def bondContractDetails(self, reqId: int, contractDetails: ContractDetails):
        super().bondContractDetails(reqId, contractDetails)

    # ! [bondcontractdetails]

    @iswrapper
    # ! [contractdetailsend]
    def contractDetailsEnd(self, reqId: int):
        super().contractDetailsEnd(reqId)
        print("ContractDetailsEnd. ", reqId, "\n")

    # ! [contractdetailsend]


    @iswrapper
    # ! [symbolSamples]
    def symbolSamples(self, reqId: int,
                      contractDescriptions: ListOfContractDescription):
        super().symbolSamples(reqId, contractDescriptions)
        print("Symbol Samples. Request Id: ", reqId)

        for contractDescription in contractDescriptions:
            derivSecTypes = ""
            for derivSecType in contractDescription.DerivativeSecTypes:
                derivSecTypes += derivSecType
                derivSecTypes += " "
            print("Contract: conId:%s, symbol:%s, secType:%s primExchange:%s, currency:%s, derivativeSecTypes:%s" % (
                contractDescription.contract.conId,
                contractDescription.contract.symbol,
                contractDescription.contract.secType,
                contractDescription.contract.primaryExch,
                contractDescription.contract.currency, derivSecTypes))

    # ! [symbolSamples]


    @iswrapper
    # ! [scannerparameters]
    def scannerParameters(self, xml: str):
        super().scannerParameters(xml)
        open('log/scanner.xml', 'w').write(xml)

    # ! [scannerparameters]


    @iswrapper
    # ! [scannerdata]
    def scannerData(self, reqId: int, rank: int, contractDetails: ContractDetails,
                    distance: str, benchmark: str, projection: str, legsStr: str):
        super().scannerData(reqId, rank, contractDetails, distance, benchmark,
                            projection, legsStr)
        print("ScannerData. ", reqId, "Rank:", rank, "Symbol:", contractDetails.summary.symbol,
              "SecType:", contractDetails.summary.secType, "Currency:", contractDetails.summary.currency,
              "Distance:", distance, "Benchmark:", benchmark,
              "Projection:", projection, "Legs String:", legsStr)

    # ! [scannerdata]


    @iswrapper
    # ! [scannerdataend]
    def scannerDataEnd(self, reqId: int):
        super().scannerDataEnd(reqId)
        print("ScannerDataEnd. ", reqId)
        # ! [scannerdataend]

    @iswrapper
    # ! [smartcomponents]
    def smartComponents(self, reqId:int, map:SmartComponentMap):
        super().smartComponents(reqId, map)
        print("smartComponents: ")
        for exch in map:
            print(exch.bitNumber, ", Exchange Name: ", exch.exchange, ", Letter: ", exch.exchangeLetter)
    # ! [smartcomponents]

    @iswrapper
    # ! [tickReqParams]
    def tickReqParams(self, tickerId:int, minTick:float, bboExchange:str, snapshotPermissions:int):
        super().tickReqParams(tickerId, minTick, bboExchange, snapshotPermissions)
        print("tickReqParams: ", tickerId, " minTick: ", minTick, " bboExchange: ", bboExchange, " snapshotPermissions: ", snapshotPermissions)
    # ! [tickReqParams]

    @iswrapper
    # ! [mktDepthExchanges]
    def mktDepthExchanges(self, depthMktDataDescriptions:ListOfDepthExchanges):
        super().mktDepthExchanges(depthMktDataDescriptions)
        print("mktDepthExchanges:")
        for desc in depthMktDataDescriptions:
            print(desc)
    # ! [mktDepthExchanges]

    @iswrapper
    # ! [fundamentaldata]
    def fundamentalData(self, reqId: TickerId, data: str):
        super().fundamentalData(reqId, data)
        print("FundamentalData. ", reqId, data)
    # ! [fundamentaldata]

    @iswrapper
    # ! [updatenewsbulletin]
    def updateNewsBulletin(self, msgId: int, msgType: int, newsMessage: str,
                           originExch: str):
        super().updateNewsBulletin(msgId, msgType, newsMessage, originExch)
        print("News Bulletins. ", msgId, " Type: ", msgType, "Message:", newsMessage,
              "Exchange of Origin: ", originExch)
        # ! [updatenewsbulletin]

        self.bulletins_cancel()

    @iswrapper
    # ! [receivefa]
    def receiveFA(self, faData: FaDataType, cxml: str):
        super().receiveFA(faData, cxml)
        print("Receiving FA: ", faData)
        open('log/fa.xml', 'w').write(cxml)

    # ! [receivefa]


    @iswrapper
    # ! [softDollarTiers]
    def softDollarTiers(self, reqId: int, tiers: list):
        super().softDollarTiers(reqId, tiers)
        print("Soft Dollar Tiers:", tiers)

    # ! [softDollarTiers]



    @iswrapper
    # ! [displaygrouplist]
    def displayGroupList(self, reqId: int, groups: str):
        super().displayGroupList(reqId, groups)
        print("DisplayGroupList. Request: ", reqId, "Groups", groups)

    # ! [displaygrouplist]


    @iswrapper
    # ! [displaygroupupdated]
    def displayGroupUpdated(self, reqId: int, contractInfo: str):
        super().displayGroupUpdated(reqId, contractInfo)
        print("displayGroupUpdated. Request:", reqId, "ContractInfo:", contractInfo)

    # ! [displaygroupupdated]


    @iswrapper
    # ! [execdetails]
    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        super().execDetails(reqId, contract, execution)
        print("ExecDetails. ", reqId, contract.symbol, contract.secType, contract.currency,
              execution.execId, execution.orderId, execution.shares)

    # ! [execdetails]


    @iswrapper
    # ! [execdetailsend]
    def execDetailsEnd(self, reqId: int):
        super().execDetailsEnd(reqId)
        print("ExecDetailsEnd. ", reqId)

    # ! [execdetailsend]


    @iswrapper
    # ! [commissionreport]
    def commissionReport(self, commissionReport: CommissionReport):
        super().commissionReport(commissionReport)
        print("CommissionReport. ", commissionReport.execId, commissionReport.commission,
              commissionReport.currency, commissionReport.realizedPNL)
        # ! [commissionreport]


def main():
    SetupLogger()
    logging.debug("now is %s", datetime.datetime.now())
    logging.getLogger().setLevel(logging.DEBUG)

    cmdLineParser = argparse.ArgumentParser("api tests")
    # cmdLineParser.add_option("-c", action="store_True", dest="use_cache", default = False, help = "use the cache")
    # cmdLineParser.add_option("-f", action="store", type="string", dest="file", default="", help="the input file")
    cmdLineParser.add_argument("-p", "--port", action="store", type=int,
                               dest="port", default=7497, help="The TCP port to use")
    cmdLineParser.add_argument("-C", "--global-cancel", action="store_true",
                               dest="global_cancel", default=False,
                               help="whether to trigger a globalCancel req")
    args = cmdLineParser.parse_args()
    print("Using args", args)
    logging.debug("Using args %s", args)
    # print(args)


    # enable logging when member vars are assigned
    from ibapi import utils
    from ibapi.order import Order
    Order.__setattr__ = utils.setattr_log
    from ibapi.contract import Contract, UnderComp
    Contract.__setattr__ = utils.setattr_log
    UnderComp.__setattr__ = utils.setattr_log
    from ibapi.tag_value import TagValue
    TagValue.__setattr__ = utils.setattr_log
    TimeCondition.__setattr__ = utils.setattr_log
    ExecutionCondition.__setattr__ = utils.setattr_log
    MarginCondition.__setattr__ = utils.setattr_log
    PriceCondition.__setattr__ = utils.setattr_log
    PercentChangeCondition.__setattr__ = utils.setattr_log
    VolumeCondition.__setattr__ = utils.setattr_log

    # from inspect import signature as sig
    # import code code.interact(local=dict(globals(), **locals()))
    # sys.exit(1)

    # tc = TestClient(None)
    # tc.reqMktData(1101, ContractSamples.USStockAtSmart(), "", False, None)
    # print(tc.reqId2nReq)
    # sys.exit(1)

    try:
        app = TestApp()
        if args.global_cancel:
            app.globalCancelOnly = True
        # ! [connect]
        app.connect("127.0.0.1", args.port, clientId=0)
        print("serverVersion:%s connectionTime:%s" % (app.serverVersion(),
                                                      app.twsConnectionTime()))
        # ! [connect]
        app.run()
    except:
        raise
    finally:
        app.dumpTestCoverageSituation()
        app.dumpReqAnsErrSituation()


if __name__ == "__main__":
    main()
