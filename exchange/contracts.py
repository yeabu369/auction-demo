from pyteal import *

def approval_program():
    seller_key = Bytes("seller")
    stock_id_key = Bytes("stock_id")
    start_time_key = Bytes("start")
    end_time_key = Bytes("end")
    reserve_amount_key = Bytes("reserve_amount")
    min_bid_increment_key = Bytes("min_bid_inc")
    num_bids_key = Bytes("num_bids")
    lead_bid_amount_key = Bytes("bid_amount")
    lead_bid_account_key = Bytes("bid_account")

    @Subroutine(TealType.none)
    def closeStockTo(assetID: Expr, account: Expr) -> Expr:
        asset_holding = AssetHolding.balance(
            Global.current_application_address(), assetID
        )
        return Seq(
            asset_holding,
            If(asset_holding.hasValue()).Then(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.AssetTransfer,
                            TxnField.xfer_asset: assetID,
                            TxnField.asset_close_to: account,
                        }
                    ),
                    InnerTxnBuilder.Submit(),
                )
            ),
        )

    @Subroutine(TealType.none)
    def repayPreviousLeadBidder(prevLeadBidder: Expr, prevLeadBidAmount: Expr) -> Expr:
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.amount: prevLeadBidAmount - Global.min_txn_fee(),
                    TxnField.receiver: prevLeadBidder,
                }
            ),
            InnerTxnBuilder.Submit(),
        )

    @Subroutine(TealType.none)
    def closeAccountTo(account: Expr) -> Expr:
        return If(Balance(Global.current_application_address()) != Int(0)).Then(
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.Payment,
                        TxnField.close_remainder_to: account,
                    }
                ),
                InnerTxnBuilder.Submit(),
            )
        )

    on_create_start_time = Btoi(Txn.application_args[2])
    on_create_end_time = Btoi(Txn.application_args[3])
    on_create = Seq(
        App.globalPut(seller_key, Txn.application_args[0]),
        App.globalPut(stock_id_key, Btoi(Txn.application_args[1])),
        App.globalPut(start_time_key, on_create_start_time),
        App.globalPut(end_time_key, on_create_end_time),
        App.globalPut(reserve_amount_key, Btoi(Txn.application_args[4])),
        App.globalPut(min_bid_increment_key, Btoi(Txn.application_args[5])),
        App.globalPut(lead_bid_account_key, Global.zero_address()),
        Assert(
            And(
                Global.latest_timestamp() < on_create_start_time,
                on_create_start_time < on_create_end_time,
                # TODO: should we impose a maximum exchange length?
            )
        ),
        Approve(),
    )

    on_setup = Seq(
        Assert(Global.latest_timestamp() < App.globalGet(start_time_key)),
        # opt into Stock asset -- because you can't opt in if you're already opted in, this is what
        # we'll use to make sure the contract has been set up
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(stock_id_key),
                TxnField.asset_receiver: Global.current_application_address(),
            }
        ),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    on_bid_txn_index = Txn.group_index() - Int(1)
    on_bid_stock_holding = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(stock_id_key)
    )
    on_bid = Seq(
        on_bid_stock_holding,
        Assert(
            And(
                # the exchange has been set up
                on_bid_stock_holding.hasValue(),
                on_bid_stock_holding.value() > Int(0),
                # the exchange has started
                App.globalGet(start_time_key) <= Global.latest_timestamp(),
                # the exchange has not ended
                Global.latest_timestamp() < App.globalGet(end_time_key),
                # the actual bid payment is before the app call
                Gtxn[on_bid_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_bid_txn_index].sender() == Txn.sender(),
                Gtxn[on_bid_txn_index].receiver()
                == Global.current_application_address(),
                Gtxn[on_bid_txn_index].amount() >= Global.min_txn_fee(),
            )
        ),
        If(
            Gtxn[on_bid_txn_index].amount()
            >= App.globalGet(lead_bid_amount_key) + App.globalGet(min_bid_increment_key)
        ).Then(
            Seq(
                If(App.globalGet(lead_bid_account_key) != Global.zero_address()).Then(
                    repayPreviousLeadBidder(
                        App.globalGet(lead_bid_account_key),
                        App.globalGet(lead_bid_amount_key),
                    )
                ),
                App.globalPut(lead_bid_amount_key, Gtxn[on_bid_txn_index].amount()),
                App.globalPut(lead_bid_account_key, Gtxn[on_bid_txn_index].sender()),
                App.globalPut(num_bids_key, App.globalGet(num_bids_key) + Int(1)),
                Approve(),
            )
        ),
        Reject(),
    )

    on_call_method = Txn.application_args[0]
    on_call = Cond(
        [on_call_method == Bytes("setup"), on_setup],
        [on_call_method == Bytes("bid"), on_bid],
    )

    on_delete = Seq(
        If(Global.latest_timestamp() < App.globalGet(start_time_key)).Then(
            Seq(
                # the exchange has not yet started, it's ok to delete
                Assert(
                    Or(
                        # sender must either be the seller or the exchange creator
                        Txn.sender() == App.globalGet(seller_key),
                        Txn.sender() == Global.creator_address(),
                    )
                ),
                # if the exchange contract account has opted into the stock, close it out
                closeStockTo(App.globalGet(stock_id_key), App.globalGet(seller_key)),
                # if the exchange contract still has funds, send them all to the seller
                closeAccountTo(App.globalGet(seller_key)),
                Approve(),
            )
        ),
        If(App.globalGet(end_time_key) <= Global.latest_timestamp()).Then(
            Seq(
                # the exchange has ended, pay out assets
                If(App.globalGet(lead_bid_account_key) != Global.zero_address())
                .Then(
                    If(
                        App.globalGet(lead_bid_amount_key)
                        >= App.globalGet(reserve_amount_key)
                    )
                    .Then(
                        # the exchange was successful: send lead bid account the stock
                        closeStockTo(
                            App.globalGet(stock_id_key),
                            App.globalGet(lead_bid_account_key),
                        )
                    )
                    .Else(
                        Seq(
                            # the exchange was not successful because the reserve was not met: return
                            # the stock to the seller and repay the lead bidder
                            closeStockTo(
                                App.globalGet(stock_id_key), App.globalGet(seller_key)
                            ),
                            repayPreviousLeadBidder(
                                App.globalGet(lead_bid_account_key),
                                App.globalGet(lead_bid_amount_key),
                            ),
                        )
                    )
                )
                .Else(
                    # the exchange was not successful because no bids were placed: return the stock to the seller
                    closeStockTo(App.globalGet(stock_id_key), App.globalGet(seller_key))
                ),
                # send remaining funds to the seller
                closeAccountTo(App.globalGet(seller_key)),
                Approve(),
            )
        ),
        Reject(),
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        [
            Txn.on_completion() == OnComplete.DeleteApplication,
            on_delete,
        ],
        [
            Or(
                Txn.on_completion() == OnComplete.OptIn,
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.UpdateApplication,
            ),
            Reject(),
        ],
    )

    return program


def clear_state_program():
    return Approve()


if __name__ == "__main__":
    with open("exchange_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("exchange_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)
