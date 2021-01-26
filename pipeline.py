import os
import zmq
import json
import time
import h5py
import numpy as np
from multiprocessing import Process
from azint import AzimuthalIntegrator
from bitshuffle import decompress_lz4
import fabio 

def zmq_worker(ai: AzimuthalIntegrator, host: str, port: int):
    context = zmq.Context()
    pull_sock = context.socket(zmq.PULL)
    pull_sock.connect('tcp://%s:%d' %(host, port))
    push_sock = context.socket(zmq.PUSH)
    push_sock.connect('tcp://localhost:5550')
    
    while True:
        parts = pull_sock.recv_multipart(copy=False)
        header = json.loads(parts[0].bytes)
        #print(header)
        if header['htype'] == 'image':
            img = decompress_lz4(parts[1].buffer, header['shape'], np.dtype(header['type']))
            res = ai.integrate(img)
            header['type'] = 'float32'
            header['shape'] = res.shape
            header['compression'] = 'none'
            push_sock.send_json(header, flags=zmq.SNDMORE)
            push_sock.send(res)
        else:
            push_sock.send_json(header)
    ai.close()
            
            
def hdf5_worker(ai: AzimuthalIntegrator, filename: str, worker_id: int, nworkers: int):
    context = zmq.Context()
    push_sock = context.socket(zmq.PUSH)
    push_sock.connect('tcp://localhost:5550')
    fh = h5py.File(filename, 'r')
    dset = fh['/entry/measurement/Eiger/data']
    nimages = len(dset)
    
    if worker_id == 0:
        header = {'htype': 'header',
                  'msg_number': -1,
                  'filename': filename}
        push_sock.send_json(header)
    
    for i in range(worker_id, nimages, nworkers):
        img = dset[i]
        res = ai.integrate(img)
        header = {'htype': 'image',
                  'msg_number': i,
                  'type': 'float32',
                  'shape': res.shape,
                  'compression': 'none'}
        push_sock.send_json(header, flags=zmq.SNDMORE)
        push_sock.send(res)
        
    if worker_id == 0:
        header = {'htype': 'series_end',
                  'msg_number': nimages}
        push_sock.send_json(header)
            
def ordered_recv(sock):
    cache = {}
    next_msg_number = -1
    while True:
        parts = sock.recv_multipart()
        header = json.loads(parts[0])
        #print('ordered_recv', header)
        msg_number = header['msg_number']
        if header['htype'] == 'header':
            next_msg_number = msg_number
        if msg_number == next_msg_number:
            yield msg_number, parts
            next_msg_number += 1
            while next_msg_number in cache:
                data = cache.pop(next_msg_number)
                yield next_msg_number, data
                next_msg_number += 1
        else:
            cache[msg_number] = parts
    

def collector(ai: AzimuthalIntegrator, base_folder: str):
    context = zmq.Context()
    pull_sock = context.socket(zmq.PULL)
    pull_sock.bind('tcp://*:5550')
    fh = None
    dset = None
    for index, parts in ordered_recv(pull_sock):
        header = json.loads(parts[0])
        print('collector', index, header)
        htype = header['htype']
        if htype == 'image':
            res = np.frombuffer(parts[1], header['type']).reshape(header['shape'])
            if fh:
                if not dset:
                    fh.create_dataset('q', data=ai.q)
                    if ai.phi:
                        fh.create_dataset('phi', data=ai.phi)
                    dset = fh.create_dataset('cake', dtype=np.float32, 
                                               shape=(0, *res.shape), 
                                               maxshape=(None, *res.shape),
                                               chunks=(1, *res.shape))
                n = dset.shape[0]
                dset.resize(n+1, axis=0)
                dset[n] = res

        elif htype == 'header':
            filename = header['filename']
            if filename:
                path, fname = os.path.split(filename)
                output_folder = os.path.join(base_folder, path.split(os.sep)[-1])
                output_file = os.path.join(output_folder, fname)
                if not os.path.exists(output_folder):
                    os.mkdir(output_folder)
                print(output_file)
                fh = h5py.File(output_file, 'w')
            else:
                fh = None
            dset = None
                
        elif htype == 'series_end':
            print('end')
            if fh:
                fh.close()

if __name__ == '__main__':
    poni_file = 'test.poni'
    host = 'localhost'
    port = 22001
    pixel_size = 75.0e-6
    n_splitting = 4
    nworkers = 4
    mask = fabio.open('mask.tif').data
    output_folder = '/tmp'
    print(mask.shape)
    phi_bins = np.linspace(-np.pi, np.pi, 721)
    ai = AzimuthalIntegrator(poni_file, mask.shape, pixel_size, n_splitting, mask, [2000,])
    #filename = '../streaming-receiver/test.h5'
    procs = []
    for i in range(nworkers):
        p = Process(target=zmq_worker, args=(ai, host, port))
        #p = Process(target=hdf5_worker, args=(ai, filename, i, nworkers))
        p.start()
        procs.append(p)
        
        
    collector(ai, output_folder)
        
    for i in range(nworkers):
        procs[i].join()
