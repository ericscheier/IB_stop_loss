from EasyTws import main, unrealized_pnl_callbacks


def unrealized_pnl_callback(val, contract):
    print("callback: ", val, contract)

if __name__ == "__main__":
    unrealized_pnl_callbacks.append(unrealized_pnl_callback)
    main()
