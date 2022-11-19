from time import time, sleep

import pytest

from algosdk import account, encoding
from algosdk.logic import get_application_address

from .operations import createExchangeApp, setupExchangeApp, placeBid, closeTrade
from .util import getBalances, getAppGlobalState, getLastBlockTimestamp
from .testing.setup import getAlgodClient
from .testing.resources import getTemporaryAccount, optInToAsset, createDummyAsset


def test_create():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    _, seller_addr = account.generate_account()  # random address

    stockID = 1  # fake ID
    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 60  # end time is 1 minute after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller_addr,
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    actual = getAppGlobalState(client, appID)
    expected = {
        b"seller": encoding.decode_address(seller_addr),
        b"stock_id": stockID,
        b"start": startTime,
        b"end": endTime,
        b"reserve_amount": reserve,
        b"min_bid_inc": increment,
        b"bid_account": bytes(32),  # decoded zero address
    }

    assert actual == expected


def test_setup():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 60  # end time is 1 minute after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    actualState = getAppGlobalState(client, appID)
    expectedState = {
        b"seller": encoding.decode_address(seller.getAddress()),
        b"stock_id": stockID,
        b"start": startTime,
        b"end": endTime,
        b"reserve_amount": reserve,
        b"min_bid_inc": increment,
        b"bid_account": bytes(32),  # decoded zero address
    }

    assert actualState == expectedState

    actualBalances = getBalances(client, get_application_address(appID))
    expectedBalances = {0: 2 * 100_000 + 2 * 1_000, stockID: stockAmount}

    assert actualBalances == expectedBalances


def test_first_bid_before_start():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 5 * 60  # start time is 5 minutes in the future
    endTime = startTime + 60  # end time is 1 minute after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    bidder = getTemporaryAccount(client)

    _, lastRoundTime = getLastBlockTimestamp(client)
    assert lastRoundTime < startTime

    with pytest.raises(Exception):
        bidAmount = 500_000  # 0.5 Algos
        placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)


def test_first_bid():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 60  # end time is 1 minute after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    bidder = getTemporaryAccount(client)

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < startTime + 5:
        sleep(startTime + 5 - lastRoundTime)

    bidAmount = 500_000  # 0.5 Algos
    placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)

    actualState = getAppGlobalState(client, appID)
    expectedState = {
        b"seller": encoding.decode_address(seller.getAddress()),
        b"stock_id": stockID,
        b"start": startTime,
        b"end": endTime,
        b"reserve_amount": reserve,
        b"min_bid_inc": increment,
        b"num_bids": 1,
        b"bid_amount": bidAmount,
        b"bid_account": encoding.decode_address(bidder.getAddress()),
    }

    assert actualState == expectedState

    actualBalances = getBalances(client, get_application_address(appID))
    expectedBalances = {0: 2 * 100_000 + 2 * 1_000 + bidAmount, stockID: stockAmount}

    assert actualBalances == expectedBalances


def test_second_bid():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 60  # end time is 1 minute after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    bidder1 = getTemporaryAccount(client)
    bidder2 = getTemporaryAccount(client)

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < startTime + 5:
        sleep(startTime + 5 - lastRoundTime)

    bid1Amount = 500_000  # 0.5 Algos
    placeBid(client=client, appID=appID, bidder=bidder1, bidAmount=bid1Amount)

    bidder1AlgosBefore = getBalances(client, bidder1.getAddress())[0]

    with pytest.raises(Exception):
        bid2Amount = bid1Amount + 1_000  # increase is less than min increment amount
        placeBid(
            client=client,
            appID=appID,
            bidder=bidder2,
            bidAmount=bid2Amount,
        )

    bid2Amount = bid1Amount + increment
    placeBid(client=client, appID=appID, bidder=bidder2, bidAmount=bid2Amount)

    actualState = getAppGlobalState(client, appID)
    expectedState = {
        b"seller": encoding.decode_address(seller.getAddress()),
        b"stock_id": stockID,
        b"start": startTime,
        b"end": endTime,
        b"reserve_amount": reserve,
        b"min_bid_inc": increment,
        b"num_bids": 2,
        b"bid_amount": bid2Amount,
        b"bid_account": encoding.decode_address(bidder2.getAddress()),
    }

    assert actualState == expectedState

    actualAppBalances = getBalances(client, get_application_address(appID))
    expectedAppBalances = {0: 2 * 100_000 + 2 * 1_000 + bid2Amount, stockID: stockAmount}

    assert actualAppBalances == expectedAppBalances

    bidder1AlgosAfter = getBalances(client, bidder1.getAddress())[0]

    # bidder1 should receive a refund of their bid, minus the txn fee
    assert bidder1AlgosAfter - bidder1AlgosBefore >= bid1Amount - 1_000


def test_close_before_start():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 5 * 60  # start time is 5 minutes in the future
    endTime = startTime + 60  # end time is 1 minute after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    _, lastRoundTime = getLastBlockTimestamp(client)
    assert lastRoundTime < startTime

    closeTrade(client, appID, seller)

    actualAppBalances = getBalances(client, get_application_address(appID))
    expectedAppBalances = {0: 0}

    assert actualAppBalances == expectedAppBalances

    sellerStockBalance = getBalances(client, seller.getAddress())[stockID]
    assert sellerStockBalance == stockAmount


def test_close_no_bids():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 30  # end time is 30 seconds after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < endTime + 5:
        sleep(endTime + 5 - lastRoundTime)

    closeTrade(client, appID, seller)

    actualAppBalances = getBalances(client, get_application_address(appID))
    expectedAppBalances = {0: 0}

    assert actualAppBalances == expectedAppBalances

    sellerStockBalance = getBalances(client, seller.getAddress())[stockID]
    assert sellerStockBalance == stockAmount


def test_close_reserve_not_met():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 30  # end time is 30 seconds after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    bidder = getTemporaryAccount(client)

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < startTime + 5:
        sleep(startTime + 5 - lastRoundTime)

    bidAmount = 500_000  # 0.5 Algos
    placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)

    bidderAlgosBefore = getBalances(client, bidder.getAddress())[0]

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < endTime + 5:
        sleep(endTime + 5 - lastRoundTime)

    closeTrade(client, appID, seller)

    actualAppBalances = getBalances(client, get_application_address(appID))
    expectedAppBalances = {0: 0}

    assert actualAppBalances == expectedAppBalances

    bidderAlgosAfter = getBalances(client, bidder.getAddress())[0]

    # bidder should receive a refund of their bid, minus the txn fee
    assert bidderAlgosAfter - bidderAlgosBefore >= bidAmount - 1_000

    sellerStockBalance = getBalances(client, seller.getAddress())[stockID]
    assert sellerStockBalance == stockAmount


def test_close_reserve_met():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    seller = getTemporaryAccount(client)

    stockAmount = 1
    stockID = createDummyAsset(client, stockAmount, seller)

    startTime = int(time()) + 10  # start time is 10 seconds in the future
    endTime = startTime + 30  # end time is 30 seconds after start
    reserve = 1_000_000  # 1 Algo
    increment = 100_000  # 0.1 Algo

    appID = createExchangeApp(
        client=client,
        sender=creator,
        seller=seller.getAddress(),
        stockID=stockID,
        startTime=startTime,
        endTime=endTime,
        reserve=reserve,
        minBidIncrement=increment,
    )

    setupExchangeApp(
        client=client,
        appID=appID,
        funder=creator,
        stockHolder=seller,
        stockID=stockID,
        stockAmount=stockAmount,
    )

    sellerAlgosBefore = getBalances(client, seller.getAddress())[0]

    bidder = getTemporaryAccount(client)

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < startTime + 5:
        sleep(startTime + 5 - lastRoundTime)

    bidAmount = reserve
    placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)

    optInToAsset(client, stockID, bidder)

    _, lastRoundTime = getLastBlockTimestamp(client)
    if lastRoundTime < endTime + 5:
        sleep(endTime + 5 - lastRoundTime)

    closeTrade(client, appID, seller)

    actualAppBalances = getBalances(client, get_application_address(appID))
    expectedAppBalances = {0: 0}

    assert actualAppBalances == expectedAppBalances

    bidderStockBalance = getBalances(client, bidder.getAddress())[stockID]

    assert bidderStockBalance == stockAmount

    actualSellerBalances = getBalances(client, seller.getAddress())

    assert len(actualSellerBalances) == 2
    # seller should receive the bid amount, minus the txn fee
    assert actualSellerBalances[0] >= sellerAlgosBefore + bidAmount - 1_000
    assert actualSellerBalances[stockID] == 0
