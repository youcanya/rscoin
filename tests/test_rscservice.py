from base64 import b64encode, b64decode
from hashlib import sha256

import rscoin
from rscoin.rscservice import RSCFactory

from twisted.test.proto_helpers import StringTransport
import os.path
from os import urandom

import pytest

@pytest.fixture
def sometx():
    secret = "A" * 32
    public = rscoin.Key(secret, public=False).pub.export()
    directory = [(public, "127.0.0.1", 8080)]

    factory = RSCFactory(secret, directory, None)
    
    # Build one transaction
    k1 = rscoin.Key(urandom(32), public=False)
    k2 = rscoin.Key(urandom(32), public=False)

    tx1 = rscoin.Tx([], [rscoin.OutputTx(k1.id(), 100)])
    tx2 = rscoin.Tx([], [rscoin.OutputTx(k2.id(), 150)])

    tx3 = rscoin.Tx([rscoin.InputTx(tx1.id(), 0), rscoin.InputTx(tx2.id(), 0)], [rscoin.OutputTx(k1.id(), 250)])
    
    for kv, vv in tx1.get_utxo_out_entries() + tx2.get_utxo_out_entries():
        factory.db[kv] = vv

    # Run the protocol
    instance = factory.buildProtocol(None)
    tr = StringTransport()
    instance.makeConnection(tr)

    return (factory, instance, tr), (k1, k2, tx1, tx2, tx3)

def test_factory():
    secret = "A" * 32
    public = rscoin.Key(secret, public=False).pub.export()
    directory = [(public, "127.0.0.1", 8080)]

    factory = RSCFactory(secret, directory, None)
    assert os.path.exists(factory.dbname)

def test_authorities():
    chars = ["A", "B", "C", "D", "E", "F"]
    directory = [(c* 32, "127.0.0.1", 8080) for c in chars]

    secret = "X"*32
    factory = RSCFactory(secret, directory, None)

    assert factory.get_authorities("AXX")[-1][0] == "E"
    assert factory.get_authorities("FXX")[-1][0] == "D"


def test_TxQuery(sometx):
    (factory, instance, tr), (k1, k2, tx1, tx2, tx3) = sometx


    tx4 = rscoin.Tx([rscoin.InputTx(tx1.id(), 0)], [rscoin.OutputTx(k1.id(), 100)])


    for kv, vv in tx1.get_utxo_out_entries() + tx2.get_utxo_out_entries():
        factory.db[kv] = vv

    # Check the list is up to date
    for ik in tx3.get_utxo_in_keys():
        assert ik in factory.db

    data = (tx3, [tx1.serialize(), tx2.serialize()], 
                            [k1.export()[0], k2.export()[0]], 
                            [k1.sign(tx3.id()), k2.sign(tx3.id())])

    # Put the transaction through
    assert factory.process_TxQuery(data)

    for ik in tx3.get_utxo_in_keys():
        assert ik not in factory.db

    ## A transaction should be indepotent
    assert factory.process_TxQuery(data)
    data2 = (tx4, [tx1.serialize()], 
                            [k1.export()[0]], 
                            [k1.sign(tx3.id())])

    assert not factory.process_TxQuery(data2)

def test_TxQuery_serialize(sometx):
    (factory, instance, tr), (k1, k2, tx1, tx2, tx3) = sometx

    # Check the list is up to date
    for ik in tx3.get_utxo_in_keys():
        assert ik in factory.db

    data = map(b64encode, [tx3.serialize(), tx1.serialize(), tx2.serialize(), 
                k1.export()[0], k2.export()[0], k1.sign(tx3.id()), k2.sign(tx3.id())])

    H = sha256(" ".join(data)).digest()

    data = " ".join(["Query", str(len(data))] + data)

    instance.lineReceived(data)
    response = tr.value()
    
    k, s = map(b64decode, response.split(" ")[1:])
    assert factory.key.verify(H, s)

def test_TxCommit(sometx):
    (factory, instance, tr), (k1, k2, tx1, tx2, tx3) = sometx

    # Check the list is up to date
    for ik in tx3.get_utxo_in_keys():
        assert ik in factory.db

    data1 = map(b64encode, [tx3.serialize(), tx1.serialize(), tx2.serialize(), 
                k1.export()[0], k2.export()[0], k1.sign(tx3.id()), k2.sign(tx3.id())])

    H = sha256(" ".join(data1)).digest()

    data = " ".join(["Query", str(len(data1))] + data1)

    instance.lineReceived(data)
    response = tr.value()
    
    k, s = map(b64decode, response.split(" ")[1:])
    k2 = rscoin.Key(k)
    assert factory.key.verify(H, s)
    assert k2.verify(H, s)

    ## Now we test the Commit
    tr.clear()
    data = " ".join(["Commit", str(len(data1))] + data1 + map(b64encode, [k, s]))
    instance.lineReceived(data)
    
    flag, pub, sig = tr.value().split(" ")
    assert factory.key.verify(tx3.id(), b64decode(sig))

    k3 = rscoin.Key(b64decode(pub))
    assert k3.verify(tx3.id(), b64decode(sig))
    