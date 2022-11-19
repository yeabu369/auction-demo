from typing import Tuple, List

from algosdk.v2client.algod import AlgodClient
from algosdk.future import transaction
from algosdk.logic import get_application_address
from algosdk import account, encoding

from pyteal import compileTeal, Mode

from .account import Account
from .contracts import approval_program, clear_state_program
from .util import (
    waitForTransaction,
    fullyCompileContract,
    getAppGlobalState,
)

APPROVAL_PROGRAM = b""
CLEAR_STATE_PROGRAM = b""


def getContracts(client: AlgodClient) -> Tuple[bytes, bytes]:
    """Get the compiled TEAL contracts for the exchange.

    Args:
        client: An algod client that has the ability to compile TEAL programs.

    Returns:
        A tuple of 2 byte strings. The first is the approval program, and the
        second is the clear state program.
    """
    global APPROVAL_PROGRAM
    global CLEAR_STATE_PROGRAM

    if len(APPROVAL_PROGRAM) == 0:
        APPROVAL_PROGRAM = fullyCompileContract(client, approval_program())
        CLEAR_STATE_PROGRAM = fullyCompileContract(client, clear_state_program())

    return APPROVAL_PROGRAM, CLEAR_STATE_PROGRAM


def createExchangeApp(
    client: AlgodClient,
    sender: Account,
    seller: str,
    stockID: int,
    startTime: int,
    endTime: int,
    reserve: int,
    minBidIncrement: int,
) -> int:
    """Create a new exchange.

    Args:
        client: An algod client.
        sender: The account that will create the exchange application.
        seller: The address of the seller that currently holds the Stock being
            exchanged.
        stockID: The ID of the Stock being exchanged.
        startTime: A UNIX timestamp representing the start time of the exchange.
            This must be greater than the current UNIX timestamp.
        endTime: A UNIX timestamp representing the end time of the exchange. This
            must be greater than startTime.
        reserve: The reserve amount of the exchange. If the exchange ends without
            a bid that is equal to or greater than this amount, the exchange will
            fail, meaning the bid amount will be refunded to the lead bidder and
            the Stock will return to the seller.
        minBidIncrement: The minimum different required between a new bid and
            the current leading bid.

    Returns:
        The ID of the newly created exchange app.
    """
    approval, clear = getContracts(client)

    globalSchema = transaction.StateSchema(num_uints=7, num_byte_slices=2)
    localSchema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

    app_args = [
        encoding.decode_address(seller),
        stockID.to_bytes(8, "big"),
        startTime.to_bytes(8, "big"),
        endTime.to_bytes(8, "big"),
        reserve.to_bytes(8, "big"),
        minBidIncrement.to_bytes(8, "big"),
    ]

    txn = transaction.ApplicationCreateTxn(
        sender=sender.getAddress(),
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval,
        clear_program=clear,
        global_schema=globalSchema,
        local_schema=localSchema,
        app_args=app_args,
        sp=client.suggested_params(),
    )

    signedTxn = txn.sign(sender.getPrivateKey())

    client.send_transaction(signedTxn)

    response = waitForTransaction(client, signedTxn.get_txid())
    assert response.applicationIndex is not None and response.applicationIndex > 0
    return response.applicationIndex


def setupExchangeApp(
    client: AlgodClient,
    appID: int,
    funder: Account,
    stockHolder: Account,
    stockID: int,
    stockAmount: int,
) -> None:
    """Finish setting up an exchange.

    This operation funds the app exchange escrow account, opts that account into
    the Stock, and sends the Stock to the escrow account, all in one atomic
    transaction group. The exchange must not have started yet.

    The escrow account requires a total of 0.203 Algos for funding. See the code
    below for a breakdown of this amount.

    Args:
        client: An algod client.
        appID: The app ID of the exchange.
        funder: The account providing the funding for the escrow account.
        stockHolder: The account holding the Stock.
        stockID: The Stock ID.
        stockAmount: The Stock amount being exchanged. Some Stocks has a total supply
            of 1, while others are fractional Stocks with a greater total supply,
            so use a value that makes sense for the Stock being exchanged.
    """
    appAddr = get_application_address(appID)

    suggestedParams = client.suggested_params()

    fundingAmount = (
        # min account balance
        100_000
        # additional min balance to opt into Stock
        + 100_000
        # 3 * min txn fee
        + 3 * 1_000
    )

    fundAppTxn = transaction.PaymentTxn(
        sender=funder.getAddress(),
        receiver=appAddr,
        amt=fundingAmount,
        sp=suggestedParams,
    )

    setupTxn = transaction.ApplicationCallTxn(
        sender=funder.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"setup"],
        foreign_assets=[stockID],
        sp=suggestedParams,
    )

    fundStockTxn = transaction.AssetTransferTxn(
        sender=stockHolder.getAddress(),
        receiver=appAddr,
        index=stockID,
        amt=stockAmount,
        sp=suggestedParams,
    )

    transaction.assign_group_id([fundAppTxn, setupTxn, fundStockTxn])

    signedFundAppTxn = fundAppTxn.sign(funder.getPrivateKey())
    signedSetupTxn = setupTxn.sign(funder.getPrivateKey())
    signedFundStockTxn = fundStockTxn.sign(stockHolder.getPrivateKey())

    client.send_transactions([signedFundAppTxn, signedSetupTxn, signedFundStockTxn])

    waitForTransaction(client, signedFundAppTxn.get_txid())


def placeBid(client: AlgodClient, appID: int, bidder: Account, bidAmount: int) -> None:
    """Place a bid on an active exchange.

    Args:
        client: An Algod client.
        appID: The app ID of the exchange.
        bidder: The account providing the bid.
        bidAmount: The amount of the bid.
    """
    appAddr = get_application_address(appID)
    appGlobalState = getAppGlobalState(client, appID)

    stockID = appGlobalState[b"stock_id"]

    if any(appGlobalState[b"bid_account"]):
        # if "bid_account" is not the zero address
        prevBidLeader = encoding.encode_address(appGlobalState[b"bid_account"])
    else:
        prevBidLeader = None

    suggestedParams = client.suggested_params()

    payTxn = transaction.PaymentTxn(
        sender=bidder.getAddress(),
        receiver=appAddr,
        amt=bidAmount,
        sp=suggestedParams,
    )

    appCallTxn = transaction.ApplicationCallTxn(
        sender=bidder.getAddress(),
        index=appID,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[b"bid"],
        foreign_assets=[stockID],
        # must include the previous lead bidder here to the app can refund that bidder's payment
        accounts=[prevBidLeader] if prevBidLeader is not None else [],
        sp=suggestedParams,
    )

    transaction.assign_group_id([payTxn, appCallTxn])

    signedPayTxn = payTxn.sign(bidder.getPrivateKey())
    signedAppCallTxn = appCallTxn.sign(bidder.getPrivateKey())

    client.send_transactions([signedPayTxn, signedAppCallTxn])

    waitForTransaction(client, appCallTxn.get_txid())


def closeTrade(client: AlgodClient, appID: int, closer: Account):
    """Close an exchange.

    This action can only happen before an exchange has begun, in which case it is
    cancelled, or after an exchange has ended.

    If called after the exchange has ended and the exchange was successful, the
    Stock is transferred to the winning bidder and the exchange proceeds are
    transferred to the seller. If the exchange was not successful, the Stock and
    all funds are transferred to the seller.

    Args:
        client: An Algod client.
        appID: The app ID of the exchange.
        closer: The account initiating the close transaction. This must be
            either the seller or exchange creator if you wish to close the
            exchange before it starts. Otherwise, this can be any account.
    """
    appGlobalState = getAppGlobalState(client, appID)

    stockID = appGlobalState[b"stock_id"]

    accounts: List[str] = [encoding.encode_address(appGlobalState[b"seller"])]

    if any(appGlobalState[b"bid_account"]):
        # if "bid_account" is not the zero address
        accounts.append(encoding.encode_address(appGlobalState[b"bid_account"]))

    deleteTxn = transaction.ApplicationDeleteTxn(
        sender=closer.getAddress(),
        index=appID,
        accounts=accounts,
        foreign_assets=[stockID],
        sp=client.suggested_params(),
    )
    signedDeleteTxn = deleteTxn.sign(closer.getPrivateKey())

    client.send_transaction(signedDeleteTxn)

    waitForTransaction(client, signedDeleteTxn.get_txid())
