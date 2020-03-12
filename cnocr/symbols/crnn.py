# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
LeCun, Yann, Leon Bottou, Yoshua Bengio, and Patrick Haffner.
Gradient-based learning applied to document recognition.
Proceedings of the IEEE (1998)
"""
import mxnet as mx
from ..fit.ctc_loss import add_ctc_loss
from ..fit.lstm import lstm2


def crnn_no_lstm(hp):

    # input
    data = mx.sym.Variable('data')
    label = mx.sym.Variable('label')

    kernel_size = [(3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3)]
    padding_size = [(1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1)]
    layer_size = [min(32*2**(i+1), 512) for i in range(len(kernel_size))]

    def convRelu(i, input_data, bn=True):
        layer = mx.symbol.Convolution(name='conv-%d' % i, data=input_data, kernel=kernel_size[i], pad=padding_size[i],
                                      num_filter=layer_size[i])
        if bn:
            layer = mx.sym.BatchNorm(data=layer, name='batchnorm-%d' % i)
        layer = mx.sym.LeakyReLU(data=layer,name='leakyrelu-%d' % i)
        return layer

    net = convRelu(0, data) # bz x f x 32 x 200
    max = mx.sym.Pooling(data=net, name='pool-0_m', pool_type='max', kernel=(2, 2), stride=(2, 2))
    avg = mx.sym.Pooling(data=net, name='pool-0_a', pool_type='avg', kernel=(2, 2), stride=(2, 2))
    net = max - avg  # 16 x 100
    net = convRelu(1, net)
    net = mx.sym.Pooling(data=net, name='pool-1', pool_type='max', kernel=(2, 2), stride=(2, 2)) # bz x f x 8 x 50
    net = convRelu(2, net, True)
    net = convRelu(3, net)
    net = mx.sym.Pooling(data=net, name='pool-2', pool_type='max', kernel=(2, 2), stride=(2, 2)) # bz x f x 4 x 25
    net = convRelu(4, net, True)
    net = convRelu(5, net)
    net = mx.symbol.Pooling(data=net, kernel=(4, 1), pool_type='avg', name='pool1') # bz x f x 1 x 25

    if hp.dropout > 0:
        net = mx.symbol.Dropout(data=net, p=hp.dropout)

    net = mx.sym.transpose(data=net, axes=[1,0,2,3])  # f x bz x 1 x 25
    net = mx.sym.flatten(data=net) # f x (bz x 25)
    hidden_concat = mx.sym.transpose(data=net, axes=[1,0]) # (bz x 25) x f

    # mx.sym.transpose(net, [])
    pred = mx.sym.FullyConnected(data=hidden_concat, num_hidden=hp.num_classes) # (bz x 25) x num_classes

    if hp.loss_type:
        # Training mode, add loss
        return add_ctc_loss(pred, hp.seq_length, hp.num_label, hp.loss_type)
    else:
        # Inference mode, add softmax
        return mx.sym.softmax(data=pred, name='softmax')


def convRelu(i, input_data, kernel_size, layer_size, padding_size, bn=True):
    layer = mx.symbol.Convolution(name='conv-%d' % i, data=input_data, kernel=kernel_size, pad=padding_size,
                                  num_filter=layer_size)
    # in_channel = input_data.infer_shape()[1][0][1]
    # num_params = in_channel * kernel_size[0] * kernel_size[1] * layer_size
    # print('number of conv-%d layer parameters: %d' % (i, num_params))
    if bn:
        layer = mx.sym.BatchNorm(data=layer, name='batchnorm-%d' % i)
    layer = mx.sym.LeakyReLU(data=layer, name='leakyrelu-%d' % i)
    # layer = mx.symbol.Convolution(name='conv-%d-1x1' % i, data=layer, kernel=(1, 1), pad=(0, 0),
    #                               num_filter=layer_size[i])
    # if bn:
    #     layer = mx.sym.BatchNorm(data=layer, name='batchnorm-%d-1x1' % i)
    # layer = mx.sym.LeakyReLU(data=layer, name='leakyrelu-%d-1x1' % i)
    return layer


def bottle_conv(i, input_data, kernel_size, layer_size, padding_size, bn=True):
    bottle_channel = layer_size // 2
    layer = mx.symbol.Convolution(name='conv-%d-1-1x1' % i, data=input_data, kernel=(1, 1), pad=(0, 0),
                                  num_filter=bottle_channel)
    layer = mx.sym.LeakyReLU(data=layer, name='leakyrelu-%d-1' % i)
    layer = mx.symbol.Convolution(name='conv-%d' % i, data=layer, kernel=kernel_size, pad=padding_size,
                                  num_filter=bottle_channel)
    layer = mx.sym.LeakyReLU(data=layer, name='leakyrelu-%d-2' % i)
    layer = mx.symbol.Convolution(name='conv-%d-2-1x1' % i, data=layer, kernel=(1, 1), pad=(0, 0),
                                  num_filter=layer_size)
    # in_channel = input_data.infer_shape()[1][0][1]
    # num_params = in_channel * bottle_channel
    # num_params += bottle_channel * kernel_size[0] * kernel_size[1] * bottle_channel
    # num_params += bottle_channel * layer_size
    # print('number of bottle-conv-%d layer parameters: %d' % (i, num_params))
    if bn:
        layer = mx.sym.BatchNorm(data=layer, name='batchnorm-%d' % i)
    layer = mx.sym.LeakyReLU(data=layer, name='leakyrelu-%d' % i)
    return layer


def crnn_lstm(hp):

    # input
    data = mx.sym.Variable('data')
    label = mx.sym.Variable('label')
    # data = mx.sym.Variable('data', shape=(128, 1, 32, 280))
    # label = mx.sym.Variable('label', shape=(128, 10))

    kernel_size = [(3, 3), (3, 3), (3, 3), (3, 3), (3, 3), (3, 3)]
    padding_size = [(1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1)]
    layer_size = [min(32*2**(i+1), 512) for i in range(len(kernel_size))]

    net = convRelu(0, data, kernel_size[0], layer_size[0], padding_size[0])  # bz x 64 x 32 x 280
    # print('0', net.infer_shape()[1])
    net = convRelu(1, net, kernel_size[1], layer_size[1], padding_size[1], True)  # bz x 128 x 16 x 140
    # print('1', net.infer_shape()[1])
    net = mx.sym.Pooling(data=net, name='pool-0', pool_type='max', kernel=(2, 2), stride=(2, 2))
    # avg = mx.sym.Pooling(data=net, name='pool-0_a', pool_type='avg', kernel=(2, 2), stride=(2, 2))
    # net = max - avg  # bz x 64 x 16 x 140
    # print('2', net.infer_shape()[1])
    # res: bz x 128 x 8 x 70
    # net = mx.sym.Pooling(data=net, name='pool-1', pool_type='max', kernel=(2, 2), stride=(2, 2))
    net = convRelu(2, net, kernel_size[2], layer_size[2], padding_size[2])  # res: bz x 256 x 8 x 70
    # print('3', net.infer_shape()[1])
    net = convRelu(3, net, kernel_size[3], layer_size[3], padding_size[3], True)  # res: bz x 512 x 8 x 70
    # res: bz x 512 x 4 x 35
    x = net = mx.sym.Pooling(data=net, name='pool-1', pool_type='max', kernel=(2, 2), stride=(2, 2))
    # print('4', net.infer_shape()[1])
    net = bottle_conv(4, net, kernel_size[4], layer_size[4], padding_size[4])
    net = bottle_conv(5, net, kernel_size[5], layer_size[5], padding_size[5], True) + x
    # res: bz x 512 x 1 x 35，高度变成1的原因是pooling后没用padding
    net = mx.symbol.Pooling(data=net, name='pool-2', pool_type='max', kernel=(2, 2), stride=(2, 1))
    # print('5', net.infer_shape()[1])
    # net = mx.symbol.Convolution(name='conv-%d' % 6, data=net, kernel=(4, 1), num_filter=layer_size[5])
    net = bottle_conv(6, net, (4, 1), layer_size[5], (0, 0))
    # print('6', net.infer_shape()[1])
    # num_params = layer_size[5] * 4 * 1 * layer_size[5]
    # print('number of conv-%d layer parameters: %d' % (6, num_params))

    if hp.dropout > 0:
        net = mx.symbol.Dropout(data=net, p=hp.dropout)

    hidden_concat = lstm2(net, num_lstm_layer=hp.num_lstm_layer, num_hidden=hp.num_hidden)
    # print('sequence length:', hp.seq_length)

    pred = mx.sym.FullyConnected(data=hidden_concat, num_hidden=hp.num_classes, name='pred_fc') # (bz x 35) x num_classes
    # print('pred', pred.infer_shape()[1])
    # import pdb; pdb.set_trace()

    if hp.loss_type:
        # Training mode, add loss
        return add_ctc_loss(pred, hp.seq_length, hp.num_label, hp.loss_type)


from ..hyperparams.cn_hyperparams import CnHyperparams as Hyperparams

if __name__ == '__main__':
    hp = Hyperparams()

    init_states = {}
    init_states['data'] = (hp.batch_size, 1, hp.img_height, hp.img_width)
    init_states['label'] = (hp.batch_size, hp.num_label)

    # init_c = {('l%d_init_c' % l): (hp.batch_size, hp.num_hidden) for l in range(hp.num_lstm_layer*2)}
    # init_h = {('l%d_init_h' % l): (hp.batch_size, hp.num_hidden) for l in range(hp.num_lstm_layer*2)}
    #
    # for item in init_c:
    #     init_states[item] = init_c[item]
    # for item in init_h:
    #     init_states[item] = init_h[item]

    symbol = crnn_no_lstm(hp)
    interals = symbol.get_internals()
    _, out_shapes, _ = interals.infer_shape(**init_states)
    shape_dict = dict(zip(interals.list_outputs(), out_shapes))

    for item in shape_dict:
        print(item,shape_dict[item])


