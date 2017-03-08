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


class ReducedTwsApp(TestWrapper, TestClient):
    """
    This is the same as TestApp in Program.py but this one has been,
    for easier usage, reduced to the required functionality only.

    To add more functionality, copy here the methods you want from TestApp.

    When the connection is established, TWS will call the method nextValidId.
    Once that happens, we can add the requests that we want. In this case,
    we call the method reqAccountUpdates (which is inside accountOperations_req
    that gets called after nextValidId is received). After that call,
    TWS API will update us with the account info by calling the methods
    updateAccountValue and updatePortfolio.

    In those two methods we call the functions that have been previously set
    to be called in case of account updates (see stoploss.py).
    """

    def __init__(self):
        TestWrapper.__init__(self)
        TestClient.__init__(self, wrapper=self)
        # ! [socket_init]
        self.nKeybInt = 0
        self.started = False
        self.nextValidOrderId = None
        self.permId2ord = {}
        self.reqId2nErr = collections.defaultdict(int)

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
        self.reqAccountUpdates(True, self.account)

    @printWhenExecuting
    def accountOperations_cancel(self):
        self.reqAccountUpdates(False, self.account)

    @iswrapper
    # ! [managedaccounts]
    def managedAccounts(self, accountsList: str):
        super().managedAccounts(accountsList)
        print("Account list: ", accountsList)
        # ! [managedaccounts]

        self.account = accountsList.split(",")[0]

    @iswrapper
    # ! [updateaccountvalue]
    def updateAccountValue(self, key: str, val: str, currency: str,
                           accountName: str):
        super().updateAccountValue(key, val, currency, accountName)
        print("UpdateAccountValue. Key:", key, "Value:", val,
              "Currency:", currency, "AccountName:", accountName)

        if key == "UnrealizedPnL":
            for c in unrealized_pnl_callbacks:
                c(val, currency)
        elif key == "NetLiquidation":
            for c in net_liquid_value_callbacks:
                c(val, currency)

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

        if contract.secType == "STK":
            for c in position_pnl_callbacks:
                c(contract, position)

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


class EasyTws:
    """
    A wrapper that makes it easier to use the TWS API.

    run() must be called before other calls are made.
    """

    app = None

    def run(self):
        SetupLogger()
        logging.debug("now is %s", datetime.datetime.now())
        logging.getLogger().setLevel(logging.DEBUG)

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

        try:
            self.app = ReducedTwsApp()
            self.app.connect("127.0.0.1", 7497, clientId=0)
            print("serverVersion:%s connectionTime:%s" % (self.app.serverVersion(),
                                                          self.app.twsConnectionTime()))
            self.app.run()
        except:
            raise
        finally:
            self.app.dumpTestCoverageSituation()
            self.app.dumpReqAnsErrSituation()

    def cancel_all_orders(self):
        print("Sending a request to cancel all open orders.")
        self.app.reqGlobalCancel()

    def send_sell_market_order(self, contract, position):
        new_contract = Contract()
        new_contract.symbol = contract.symbol
        new_contract.secType = contract.secType
        new_contract.currency = contract.currency
        new_contract.exchange = "SMART"

        print("---Placing order, contract settings:")
        print("\t", new_contract.symbol)
        print("\t", new_contract.secType)
        print("\t", new_contract.currency)
        print("\t", new_contract.exchange)

        self.app.placeOrder(
            self.app.nextValidOrderId,
            new_contract,
            OrderSamples.MarketOrder("SELL", position)
        )


"""
Use the lists below to add functions that you want
to be called when TWS returns data to us.
"""
unrealized_pnl_callbacks = []
position_pnl_callbacks = []
net_liquid_value_callbacks = []
