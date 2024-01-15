# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from typing import Callable
from typing import Dict
from typing import Tuple

import numpy as np
import paddle
from paddle import nn

from ppsci.utils import logger


class Arch(nn.Layer):
    """Base class for Network."""

    input_keys: Tuple[str, ...]
    output_keys: Tuple[str, ...]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._input_transform: Callable[
            [Dict[str, paddle.Tensor]], Dict[str, paddle.Tensor]
        ] = None

        self._output_transform: Callable[
            [Dict[str, paddle.Tensor], Dict[str, paddle.Tensor]],
            Dict[str, paddle.Tensor],
        ] = None

    def forward(self, *args, **kwargs):
        raise NotImplementedError("Arch.forward is not implemented")

    @property
    def num_params(self) -> int:
        """Return number of parameters within network.

        Returns:
            int: Number of parameters.
        """
        num = 0
        for name, param in self.named_parameters():
            if hasattr(param, "shape"):
                num += np.prod(list(param.shape))
            else:
                logger.warning(f"{name} has no attribute 'shape'")
        return num

    def concat_to_tensor(
        self, data_dict: Dict[str, paddle.Tensor], keys: Tuple[str, ...], axis=-1
    ) -> Tuple[paddle.Tensor, ...]:
        """Concatenate tensors from dict in the order of given keys.

        Args:
            data_dict (Dict[str, paddle.Tensor]): Dict contains tensor.
            keys (Tuple[str, ...]): Keys tensor fetched from.
            axis (int, optional): Axis concatenate at. Defaults to -1.

        Returns:
            Tuple[paddle.Tensor, ...]: Concatenated tensor.

        Examples:
            >>> import paddle
            >>> import ppsci
            >>> model = ppsci.arch.Arch()
            >>> # fetch one tensor
            >>> out = model.concat_to_tensor({'x':paddle.to_tensor(123)}, ('x',))
            >>> print(out)
            Tensor(shape=[], dtype=int64, place=Place(gpu:0), stop_gradient=True,
                   123)
            >>> # fetch more tensors
            >>> out = model.concat_to_tensor(
            ...     {'x1':paddle.to_tensor([123]), 'x2':paddle.to_tensor([234])},
            ...     ('x1', 'x2'),
            ...     axis=0)
            >>> print(out)
            Tensor(shape=[2], dtype=int64, place=Place(gpu:0), stop_gradient=True,
                   [123, 234])

        """
        if len(keys) == 1:
            return data_dict[keys[0]]
        data = [data_dict[key] for key in keys]
        return paddle.concat(data, axis)

    def split_to_dict(
        self, data_tensor: paddle.Tensor, keys: Tuple[str, ...], axis=-1
    ) -> Dict[str, paddle.Tensor]:
        """Split tensor and wrap into a dict by given keys.

        Args:
            data_tensor (paddle.Tensor): Tensor to be split.
            keys (Tuple[str, ...]): Keys tensor mapping to.
            axis (int, optional): Axis split at. Defaults to -1.

        Returns:
            Dict[str, paddle.Tensor]: Dict contains tensor.

        Examples:
            >>> import paddle
            >>> import ppsci
            >>> model = ppsci.arch.Arch()
            >>> # split one tensor
            >>> out = model.split_to_dict(paddle.to_tensor(123), ('x',))
            >>> print(out)
            {'x': Tensor(shape=[], dtype=int64, place=Place(gpu:0), stop_gradient=True,
                   123)}
            >>> # split more tensors
            >>> out = model.split_to_dict(paddle.to_tensor([123, 234]), ('x1', 'x2'), axis=0)
            >>> print(out)
            {'x1': Tensor(shape=[1], dtype=int64, place=Place(gpu:0), stop_gradient=True,
                   [123]), 'x2': Tensor(shape=[1], dtype=int64, place=Place(gpu:0), stop_gradient=True,
                   [234])}

        """
        if len(keys) == 1:
            return {keys[0]: data_tensor}
        data = paddle.split(data_tensor, len(keys), axis=axis)
        return {key: data[i] for i, key in enumerate(keys)}

    def register_input_transform(
        self,
        transform: Callable[[Dict[str, paddle.Tensor]], Dict[str, paddle.Tensor]],
    ):
        """Register input transform.

        Args:
            transform (Callable[[Dict[str, paddle.Tensor]], Dict[str, paddle.Tensor]]):
                Input transform of network, receive a single tensor dict and return a single tensor dict.

        Examples:
            >>> import ppsci
            >>> def transform_fn(in_):
            ...     x = in_["x"]
            ...     x = 2.0 * x
            ...     input_trans = {"x": x}
            ...     return input_trans
            >>> model = ppsci.arch.Arch()
            >>> model.register_input_transform(transform_fn)

        """
        self._input_transform = transform

    def register_output_transform(
        self,
        transform: Callable[
            [Dict[str, paddle.Tensor], Dict[str, paddle.Tensor]],
            Dict[str, paddle.Tensor],
        ],
    ):
        """Register output transform.

        Args:
            transform (Callable[[Dict[str, paddle.Tensor], Dict[str, paddle.Tensor]], Dict[str, paddle.Tensor]]):
                Output transform of network, receive two single tensor dict(raw input
                and raw output) and return a single tensor dict(transformed output).

        Examples:
            >>> import ppsci
            >>> def transform_fn(in_, out):
            ...     x = in_["x"]
            ...     y = out["y"]
            ...     u = 2.0 * x * y
            ...     output_trans = {"u": u}
            ...     return output_trans
            >>> model = ppsci.arch.Arch()
            >>> model.register_output_transform(transform_fn)

        """
        self._output_transform = transform

    def freeze(self):
        """Freeze all parameters.

        Examples:
            >>> import ppsci
            >>> model = ppsci.arch.Arch()
            >>> # freeze all parameters and make model `eval`
            >>> model.freeze()

        """
        for param in self.parameters():
            param.stop_gradient = True

        self.eval()

    def unfreeze(self):
        """Unfreeze all parameters.

        Examples:
            >>> import ppsci
            >>> model = ppsci.arch.Arch()
            >>> # unfreeze all parameters and make model `train`
            >>> model.unfreeze()

        """
        for param in self.parameters():
            param.stop_gradient = False

        self.train()

    def __str__(self):
        num_fc = 0
        num_conv = 0
        num_bn = 0
        for layer in self.sublayers(include_self=True):
            if isinstance(layer, nn.Linear):
                num_fc += 1
            elif isinstance(layer, (nn.Conv2D, nn.Conv3D, nn.Conv1D)):
                num_conv += 1
            elif isinstance(layer, (nn.BatchNorm, nn.BatchNorm2D, nn.BatchNorm3D)):
                num_bn += 1

        return ", ".join(
            [
                self.__class__.__name__,
                f"input_keys = {self.input_keys}",
                f"output_keys = {self.output_keys}",
                f"num_fc = {num_fc}",
                f"num_conv = {num_conv}",
                f"num_bn = {num_bn}",
                f"num_params = {self.num_params}",
            ]
        )
