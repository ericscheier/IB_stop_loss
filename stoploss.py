import sys

from decimal import Decimal

from EasyTws import EasyTws, unrealized_pnl_callbacks, \
    position_pnl_callbacks, net_liquid_value_callbacks


class StoplossAlgo:
    """
    Implements the take profit / stop loss logic where all orders are canceled
    and all positions are closed when the unrealized P&L reaches X% of the
    liquidation value in either direction.

    Run with: python3 stoploss.py limit_percent=X
        where X is the desired percentage.
    """

    latest_unrealized_pnl = None
    latest_net_liquid_value = None

    latest_open_positions = {}

    are_positions_already_closed = False

    def __init__(self, main, limit_percent):
        self.main = main
        self.limit_percent = limit_percent

    def unrealized_pnl_callback(self, val, contract):
        if contract == "BASE":
            print("\tUnrealized P&L: ", val)
            self.latest_unrealized_pnl = Decimal(val)
            self.check_if_passed_daily_limit()

    def net_liquid_value_callback(self, val, contract):
        print("\tNet liquidation value: ", val, contract)
        self.latest_net_liquid_value = Decimal(val)
        self.check_if_passed_daily_limit()

    def position_pnl_callback(self, contract, position):
        print("\tposition_pnl_callback: ", contract.symbol, position)
        self.latest_open_positions[contract] = position

    def check_if_passed_daily_limit(self):
        if self.are_positions_already_closed:
            return

        if self.latest_unrealized_pnl is None \
                or self.latest_net_liquid_value is None:
            print("Not all needed variables have been set yet.")
            return

        percentage = \
            self.latest_unrealized_pnl / self.latest_net_liquid_value * 100

        print("Percentage daily position: {0:.2f}%".format(percentage))
        if percentage >= limit_percent:
            print("Reached the upper limit, taking profit.")
            self.cancel_orders_and_close_positions()
        elif percentage <= -limit_percent:
            print("Reached the lower limit, stopping losses.")
            self.cancel_orders_and_close_positions()

    def cancel_orders_and_close_positions(self):
        main.cancel_all_orders()
        for contract, position in self.latest_open_positions.items():
            if position > 0:
                main.send_sell_market_order(contract, position)
                print(contract)
                print("Selling " + contract.symbol + " " + str(position))
            else:
                print("Skipping negative position instrument.")

        self.are_positions_already_closed = True


if __name__ == "__main__":
    assert len(sys.argv) == 2
    arg = sys.argv[1].split("=")
    assert arg[0] == "limit_percent"

    limit_percent = Decimal(arg[1])

    main = EasyTws()

    my_algo = StoplossAlgo(main, limit_percent)
    unrealized_pnl_callbacks.append(my_algo.unrealized_pnl_callback)
    net_liquid_value_callbacks.append(my_algo.net_liquid_value_callback)
    position_pnl_callbacks.append(my_algo.position_pnl_callback)

    main.run()
