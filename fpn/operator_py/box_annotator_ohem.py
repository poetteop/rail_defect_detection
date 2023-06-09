

import mxnet as mx
import numpy as np
from distutils.util import strtobool
from config.config import config

class BoxAnnotatorOHEMOperator(mx.operator.CustomOp):
    def __init__(self, num_classes, num_reg_classes,rm_last, roi_per_img):
        super(BoxAnnotatorOHEMOperator, self).__init__()
        self._num_classes = num_classes
        self._num_reg_classes = num_reg_classes
        self._roi_per_img = roi_per_img
        self._rm_last = rm_last

    def forward(self, is_train, req, in_data, out_data, aux):

        cls_score    = in_data[0]
        bbox_pred    = in_data[1]
        labels       = in_data[2].asnumpy()
        bbox_targets = in_data[3]
        bbox_weights = in_data[4]

        if config.network.SOFTMAX_ENABLED:
            per_roi_loss_cls = mx.nd.SoftmaxActivation(cls_score) + 1e-14
        else:
            per_roi_loss_cls = cls_score + 1e-14
        per_roi_loss_cls = per_roi_loss_cls.asnumpy()
        per_roi_loss_cls = per_roi_loss_cls[np.arange(per_roi_loss_cls.shape[0], dtype='int'), labels.astype('int')]
        per_roi_loss_cls = -1 * np.log(per_roi_loss_cls)
        per_roi_loss_cls = np.reshape(per_roi_loss_cls, newshape=(-1,))

        per_roi_loss_bbox = bbox_weights * mx.nd.smooth_l1((bbox_pred - bbox_targets), scalar=1.0)
        per_roi_loss_bbox = mx.nd.sum(per_roi_loss_bbox, axis=1).asnumpy()

        # changed by Leonid to make sure all the positives are in
        total_loss = per_roi_loss_cls + per_roi_loss_bbox
        # total_loss[labels>0] += 10000

        top_k_per_roi_loss = np.argsort(total_loss)
        labels_ohem = labels
        if self._rm_last==1:
            labels_ohem[np.where(labels_ohem==self._num_classes-1)]=-1

        labels_ohem[top_k_per_roi_loss[::-1][self._roi_per_img:]] = -1
        bbox_weights_ohem = bbox_weights.asnumpy()
        bbox_weights_ohem[top_k_per_roi_loss[::-1][self._roi_per_img:]] = 0

        labels_ohem = mx.nd.array(labels_ohem)
        bbox_weights_ohem = mx.nd.array(bbox_weights_ohem)

        for ind, val in enumerate([labels_ohem, bbox_weights_ohem]):
            self.assign(out_data[ind], req[ind], val)

    def backward(self, req, out_grad, in_data, out_data, in_grad, aux):
        for i in range(len(in_grad)):
            self.assign(in_grad[i], req[i], 0)


@mx.operator.register('BoxAnnotatorOHEM')
class BoxAnnotatorOHEMProp(mx.operator.CustomOpProp):
    def __init__(self, num_classes, num_reg_classes,rm_last, roi_per_img):
        super(BoxAnnotatorOHEMProp, self).__init__(need_top_grad=False)
        self._num_classes = int(num_classes)
        self._num_reg_classes = int(num_reg_classes)
        self._roi_per_img = int(roi_per_img)
        self._rm_last = rm_last
    def list_arguments(self):
        return ['cls_score', 'bbox_pred', 'labels', 'bbox_targets', 'bbox_weights']

    def list_outputs(self):
        return ['labels_ohem', 'bbox_weights_ohem']

    def infer_shape(self, in_shape):
        labels_shape = in_shape[2]
        bbox_weights_shape = in_shape[4]

        return in_shape, \
               [labels_shape, bbox_weights_shape]

    def create_operator(self, ctx, shapes, dtypes):
        return BoxAnnotatorOHEMOperator(self._num_classes, self._num_reg_classes,self._rm_last, self._roi_per_img)

    def declare_backward_dependency(self, out_grad, in_data, out_data):
        return []
