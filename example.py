from time import time, sleep

from algosdk import account, encoding
from algosdk.logic import get_application_address
from exchange.operations import createExchangeApp, setupExchangeApp, placeBid, closeTrade
from exchange.util import (
    getBalances,
    getAppGlobalState,
    getLastBlockTimestamp,
)
from exchange.testing.setup import getAlgodClient
from exchange.testing.resources import (
    getTemporaryAccount,
    optInToAsset,
    createDummyStock,
)


def simple_farm_stock_trade():
    client = getAlgodClient()

    print("Generating temporary accounts...")
    farmer = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)
    buyer = getTemporaryAccount(client)

    print("Abebe (seller account):", seller.getAddress())
    print("Kebede (exchange farmer account):", farmer.getAddress())
    print("Chala (buyer account)", buyer.getAddress(), "\n")

    print("Abebe is generating an example stock...")
    stockAmount = 1
    stockID = createDummyStock(client, stockAmount, seller)
    print("The Stock ID is", stockID)
    print("Abebe's balances:", getBalances(client, seller.getAddress()), "\n")

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 30  # end time is 30 seconds after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo
    print("Kebede is creating an exchange that lasts 30 seconds to exchange off the stock...")
    appID = createExchangeApp(
        client=client,
        sender=farmer,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )
    print(
        "Done. The exchange app ID is",
        appID,
        "and the escrow account is",
        get_application_address(appID),
        "\n",
    )

    print("Abebe is setting up and funding stock exchange...")
    setupExchangeApp(
        client=client,
        appID=appID,
        funder=farmer,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )
    print("Done\n")

    sellerBalancesBefore = getBalances(client, seller.getAddress())
    sellerAlgosBefore = sellerBalancesBefore[0]
    print("Abebe's balances:", sellerBalancesBefore)

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < startTime + 5:
        sleep(startTime + 5 - lastRoundTime)
    actualAppBalancesBefore = getBalances(client, get_application_address(appID))
    print("Exchange escrow balances:", actualAppBalancesBefore, "\n")

    bidAmount = reserve
    buyerBalancesBefore = getBalances(client, buyer.getAddress())
    buyerAlgosBefore = buyerBalancesBefore[0]
    print("Chala wants to bid on stock, her balances:", buyerBalancesBefore)
    print("Chala is placing bid for", bidAmount, "microAlgos")

    placeBid(client=client, appID=appID, bidder=buyer, bidAmount=bidAmount)

    print("Chala is opting into stock with ID", stockID)

    optInToAsset(client, stockID, buyer)

    print("Done\n")

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < endTime + 5:
        waitTime = endTime + 5 - lastRoundTime
        print("Waiting {} seconds for the exchange to finish\n".format(waitTime))
        sleep(waitTime)

    print("Abebe is closing out the exchange\n")
    closeTrade(client, appID, seller)

    actualAppBalances = getBalances(client, get_application_address(appID))
    expectedAppBalances = {0: 0}
    print("The exchange escrow now holds the following:", actualAppBalances)
    assert actualAppBalances == expectedAppBalances

    buyerstockBalance = getBalances(client, buyer.getAddress())[stockID]
    assert buyerstockBalance == stockAmount

    actualSellerBalances = getBalances(client, seller.getAddress())
    print("Abebe's balances after exchange: ", actualSellerBalances, " Algos")
    actualbuyerBalances = getBalances(client, buyer.getAddress())
    print("Chala's balances after exchange: ", actualbuyerBalances, " Algos")
    assert len(actualSellerBalances) == 2
    # seller should receive the bid amount, minus the txn fee
    assert actualSellerBalances[0] >= sellerAlgosBefore + bidAmount - 1_000
    assert actualSellerBalances[stockID] == 0


simple_farm_stock_trade()
