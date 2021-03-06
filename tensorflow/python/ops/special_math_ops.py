# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Arithmetic Operations that don't fit into math_ops due to dependencies.

To avoid circular dependencies, some math_ops should go here.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import re
import string

from functools import reduce

from six.moves import xrange  # pylint: disable=redefined-builtin

from tensorflow.compiler.tf2xla.ops import gen_xla_ops
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.platform import tf_logging as logging
from tensorflow.python.util import deprecation
from tensorflow.python.util.tf_export import tf_export


# TODO(b/27419586) Change docstring for required dtype of x once int allowed
@tf_export('math.lbeta', v1=['math.lbeta', 'lbeta'])
@deprecation.deprecated_endpoints('lbeta')
def lbeta(x, name=None):
  r"""Computes \\(ln(|Beta(x)|)\\), reducing along the last dimension.

  Given one-dimensional `z = [z_0,...,z_{K-1}]`, we define

  $$Beta(z) = \prod_j Gamma(z_j) / Gamma(\sum_j z_j)$$

  And for `n + 1` dimensional `x` with shape `[N1, ..., Nn, K]`, we define
  $$lbeta(x)[i1, ..., in] = Log(|Beta(x[i1, ..., in, :])|)$$.

  In other words, the last dimension is treated as the `z` vector.

  Note that if `z = [u, v]`, then
  \\(Beta(z) = int_0^1 t^{u-1} (1 - t)^{v-1} dt\\), which defines the
  traditional bivariate beta function.

  If the last dimension is empty, we follow the convention that the sum over
  the empty set is zero, and the product is one.

  Args:
    x: A rank `n + 1` `Tensor`, `n >= 0` with type `float`, or `double`.
    name: A name for the operation (optional).

  Returns:
    The logarithm of \\(|Beta(x)|\\) reducing along the last dimension.
  """
  # In the event that the last dimension has zero entries, we return -inf.
  # This is consistent with a convention that the sum over the empty set 0, and
  # the product is 1.
  # This is standard.  See https://en.wikipedia.org/wiki/Empty_set.
  with ops.name_scope(name, 'lbeta', [x]):
    x = ops.convert_to_tensor(x, name='x')

    # Note reduce_sum([]) = 0.
    log_prod_gamma_x = math_ops.reduce_sum(math_ops.lgamma(x), axis=[-1])

    # Note lgamma(0) = infinity, so if x = []
    # log_gamma_sum_x = lgamma(0) = infinity, and
    # log_prod_gamma_x = lgamma(1) = 0,
    # so result = -infinity
    sum_x = math_ops.reduce_sum(x, axis=[-1])
    log_gamma_sum_x = math_ops.lgamma(sum_x)
    result = log_prod_gamma_x - log_gamma_sum_x

    return result


@tf_export('math.bessel_i0')
def bessel_i0(x, name=None):
  """Computes the Bessel i0 function of `x` element-wise.

  Modified Bessel function of order 0.

  It is preferable to use the numerically stabler function `i0e(x)` instead.

  Args:
    x: A `Tensor` or `SparseTensor`. Must be one of the following types: `half`,
      `float32`, `float64`.
    name: A name for the operation (optional).

  Returns:
    A `Tensor` or `SparseTensor`, respectively. Has the same type as `x`.

  @compatibility(scipy)
  Equivalent to scipy.special.i0
  @end_compatibility
  """
  with ops.name_scope(name, 'bessel_i0', [x]):
    return math_ops.exp(math_ops.abs(x)) * math_ops.bessel_i0e(x)


@tf_export('math.bessel_i1')
def bessel_i1(x, name=None):
  """Computes the Bessel i1 function of `x` element-wise.

  Modified Bessel function of order 1.

  It is preferable to use the numerically stabler function `i1e(x)` instead.

  Args:
    x: A `Tensor` or `SparseTensor`. Must be one of the following types: `half`,
      `float32`, `float64`.
    name: A name for the operation (optional).

  Returns:
    A `Tensor` or `SparseTensor`, respectively. Has the same type as `x`.

  @compatibility(scipy)
  Equivalent to scipy.special.i1
  @end_compatibility
  """
  with ops.name_scope(name, 'bessel_i1', [x]):
    return math_ops.exp(math_ops.abs(x)) * math_ops.bessel_i1e(x)


@ops.RegisterGradient('XlaEinsum')
def _einsum_grad(op, grad):
  equation = op.get_attr('equation')
  inputs, output = equation.split('->')
  left, right = inputs.split(',')

  return [
      gen_xla_ops.xla_einsum(
          grad,
          op.inputs[1],
          equation='{},{}->{}'.format(output, right, left),
          name=None),
      gen_xla_ops.xla_einsum(
          grad,
          op.inputs[0],
          equation='{},{}->{}'.format(output, left, right),
          name=None)
  ]


def _enclosing_tpu_context():
  # pylint: disable=protected-access
  context = ops.get_default_graph()._get_control_flow_context()
  # pylint: enable=protected-access
  while context is not None and not isinstance(
      context, control_flow_ops.XLAControlFlowContext):
    context = context.outer_context
  return context


@tf_export('einsum', 'linalg.einsum')
def einsum(equation, *inputs, **kwargs):
  """A generalized contraction between tensors of arbitrary dimension.
  
  This function returns a tensor whose elements are defined by `equation`,
  which is written in a shorthand form inspired by the Einstein summation
  convention.  As an example, consider multiplying two matrices
  A and B to form a matrix C.  The elements of C are given by:
  
  ```
    C[i,k] = sum_j A[i,j] * B[j,k]
  ```
  
  The corresponding `equation` is:
  
  ```
    ij,jk->ik
  ```
  
  In general, the `equation` is obtained from the more familiar element-wise
  equation by
    1. removing variable names, brackets, and commas,
    2. replacing "*" with ",",
    3. dropping summation signs, and
    4. moving the output to the right, and replacing "=" with "->".
  
  Many common operations can be expressed in this way.  For example:
  
  ```python
  # Matrix multiplication
  >>> einsum('ij,jk->ik', m0, m1)  # output[i,k] = sum_j m0[i,j] * m1[j, k]
  
  # Dot product
  >>> einsum('i,i->', u, v)  # output = sum_i u[i]*v[i]
  
  # Outer product
  >>> einsum('i,j->ij', u, v)  # output[i,j] = u[i]*v[j]
  
  # Transpose
  >>> einsum('ij->ji', m)  # output[j,i] = m[i,j]

  # Trace
  >>> einsum('ii', m)  # output[j,i] = trace(m) = sum_i m[i, i]

  # Batch matrix multiplication
  >>> einsum('aij,ajk->aik', s, t)  # out[a,i,k] = sum_j s[a,i,j] * t[a, j, k]
  ```

  To enable and control broadcasting, use an ellipsis.  For example, to do
  batch matrix multiplication, you could use:

  ```python
  >>> einsum('...ij,...jk->...ik', u, v)
  ```

  This function behaves like `numpy.einsum`, but does not support:

  * Subscripts where an axis appears more than once for a single input
    (e.g. `ijj,k->ik`) unless it is a trace (e.g. `ijji`).

  Args:
    equation: a `str` describing the contraction, in the same format as
      `numpy.einsum`.
    *inputs: the inputs to contract (each one a `Tensor`), whose shapes should
      be consistent with `equation`.
    name: A name for the operation (optional).
    optimize: `{False, True, 'dp', 'greedy'}`, optional
      If not `False`, the contraction sequence will be optimized before 
      building the computation graph. Note that this will be ignored if the 
      function falls back to the exponential-space implementation.
      If `False`, tensors will be contracted from left to right. 
      If `'dp'` or `'True'`, a dynamic programming approach (inspired by 
      arXiv:1304.6112) will be used to find an optimized contraction order.
      If `'greedy'`, a greedy algorithm will be used to optimize the order.
      The default value is `'True'`. 
  
  Returns:
    The contracted `Tensor`, with shape determined by `equation`.
  
  Raises:
    ValueError: If
      - the format of `equation` is incorrect,
      - the number of inputs implied by `equation` does not match `len(inputs)`,
      - an axis appears in the output subscripts but not in any of the inputs,
      - the number of dimensions of an input differs from the number of
        indices in its subscript, or
      - the input shapes are inconsistent along a particular axis.
  """
  name = kwargs.pop('name', None)
  optimize = kwargs.pop('optimize', True)
  if kwargs:
    raise TypeError('invalid keyword arguments for this function: ' + ', '.join(
        [format(key) for key in sorted(list(kwargs.keys()))]))
  with ops.name_scope(name, 'einsum', [equation, inputs]) as name:
    inputs = list(inputs)
    input_shapes = [x.get_shape() for x in inputs]
    input_axis_labels, output_axis_labels = _einsum_parse_and_resolve_equation(
        equation, input_shapes)
      
    # if dimensions are not known, optimization is not possible
    if any(None in i.shape.as_list() for i in inputs):
      optimize = False

    axis_labels = set(''.join(input_axis_labels) + output_axis_labels)

    for a in axis_labels:
      for input_labels in input_axis_labels:
        if (len(input_axis_labels) == 1 and input_labels.count(a) == 2 and
            input_labels == input_labels[::-1] and '->' not in equation):
          return math_ops.trace(inputs[0])
        if input_labels.count(a) > 1:
          raise ValueError(
              'Subscript not supported: an axis appears more than once: %s' %
              input_labels)
    for a in axis_labels:
      input_count = sum(1 for s in input_axis_labels if a in s)
      if input_count > 2 and a not in output_axis_labels:
        logging.warn(
            'Falling back to exponential-space implementation of einsum()'
            ' because index "%s" is summed over more than two inputs.', a)
        return _exponential_space_einsum(equation, *inputs)

    if _enclosing_tpu_context() is not None and len(inputs) == 2:
      return gen_xla_ops.xla_einsum(
          inputs[0], inputs[1], input_axis_labels[0] + ',' +
          input_axis_labels[1] + '->' + output_axis_labels)

    # the list seq gives the order of pairwise contractions; seq[0] is the
    # first, seq[1] the second contraction and so forth; each element of seq
    # (j,k) tells us to contract tensors j and k in the list of inputs, remove
    # them from inputs and prepend the new tensor to the list
    seq = einsum_optimize(
      [t.shape.as_list() for t in inputs],
      input_axis_labels, 
      output_axis_labels,
      optimize=optimize
    )
    
    for j, k in seq:
      if j > k: j, k = k, j
      t2, l2 = inputs.pop(k), input_axis_labels.pop(k)
      t1, l1 = inputs.pop(j), input_axis_labels.pop(j)
      axes_to_sum = (set(l1) & set(l2)) - set(output_axis_labels)
      t3, l3 = _einsum_reduction(t1, l1, t2, l2, axes_to_sum)
      inputs.insert(0, t3)
      input_axis_labels.insert(0, l3)
    
    missing_indices = set(input_axis_labels[0]) - set(output_axis_labels)

    if missing_indices:
      axis = [
          i for i, a in enumerate(input_axis_labels[0])
          if a not in output_axis_labels
      ]
      temp = math_ops.reduce_sum(inputs[0], axis=axis)
      temp_axis_labels = ''.join(
          a for a in input_axis_labels[0] if a in output_axis_labels)
    
    if sorted(input_axis_labels[0]) != sorted(output_axis_labels):
      raise ValueError('Invalid equation: %s' % equation)
    
    perm = [input_axis_labels[0].index(a) for a in output_axis_labels]
    return _transpose_if_necessary(inputs[0], perm)

  
@tf_export('einsum_optimize', 'linalg.einsum_optimize')
def einsum_optimize(ishapes, ilabels, olabels, **kwargs):

  optimize = kwargs.pop('optimize', True)

  if not optimize:
    return [(0,1)]*(len(ishapes)-1)
  elif optimize in {True, 'dp'}:
    cost_limit = kwargs.pop('cost_limit', np.inf)
    return _einsum_optimize_dp(ishapes, ilabels, olabels, cost_limit)
  elif optimize == "greedy":
    return _einsum_optimize_greedy(ishapes, ilabels, olabels)

  raise ValueError('invalid optimization strategy "{}"'.format(optimize))
  

def _einsum_parse_and_resolve_equation(equation, input_shapes):
  """Helper for einsum() that splits/resolves inputs & outputs.

  Args:
    equation: Equation string given as argument to einsum().
    input_shapes: List of the shapes of all inputs given to einsum()

  Returns:
    input_axis_labels, output_axis_labels where:
      input_axis_labels: List of length len(input_shapes) of strings
      representing the character label for each dimension of each given input,
      resolving any broadcast (...) axes,
    output_axis_labels: A string of character labels for each axes of output
      tensor, filling in missing output subscripts and broadcast axes.

  Raises:
    ValueError: If equation is in the uncorrect format, incorrect number of
      inputs given or broadcast axes "..." or output axes could not be resolved.
  """
  equation = equation.replace(' ', '')
  match = re.match('^([a-zA-Z,.]+)(->[a-zA-Z.]*)?$', equation)
  if not match:
    raise ValueError('Indices have incorrect format: %s' % equation)

  input_axis_labels = match.group(1).split(',')
  output_axis_labels = match.group(2)[2:] if match.group(2) else None

  if len(input_shapes) != len(input_axis_labels):
    raise ValueError('Got %d arguments for equation "%s", expecting %d' %
                     (len(input_shapes), equation, len(input_axis_labels)))

  # Resolve Ellipsis
  # Assign axes labels for unspecified dimensions in inputs. Labels taken
  # from unused labels. Follow numpy einsum broadcasting conventions for
  # tensors of different length and unlabeled output.
  ellipsis_axes = ''
  if '...' in equation:
    unused = ''.join([c for c in string.ascii_letters
                      if c not in ''.join(input_axis_labels)])
    for i, ax in enumerate(input_axis_labels):
      if '...' in ax:
        parts = ax.split('...')
        if len(parts) != 2:
          raise ValueError('Unable to resolve ellipsis. Excess number found.')
        if input_shapes[i].ndims is None:
          raise ValueError('Unable to statically infer ellipsis axes.')
        n = input_shapes[i].ndims - len(''.join(parts))
        if n < 0:
          raise ValueError('Ellipses lengths do not match.')
        if len(unused) < n:
          raise ValueError(
              'Unable to resolve ellipsis, too many distinct labels.')
        replace_axes = unused[-n:] if n > 0 else ''
        input_axis_labels[i] = input_axis_labels[i].replace('...',
                                                            replace_axes)
        if len(replace_axes) > len(ellipsis_axes):
          ellipsis_axes = replace_axes

    if any(['.' in ax for ax in input_axis_labels]):
      raise ValueError('period "." found outside of ellipsis')

    if output_axis_labels is not None:
      output_axis_labels = output_axis_labels.replace('...', ellipsis_axes)
      if '.' in output_axis_labels:
        raise ValueError('period "." found outside of ellipsis')

  if output_axis_labels is None:
    # infer the output subscripts if not given, assume alphabetical order,
    # but always place ellipsis axes before given.
    axis_labels = set(''.join(input_axis_labels)) - set(ellipsis_axes)
    indices = ''.join(sorted(axis_labels))
    counts = {ax: 0 for ax in indices}
    for axes_ in input_axis_labels:
      for ax in axes_:
        if ax not in ellipsis_axes:
          counts[ax] += 1

    output_axis_labels = ellipsis_axes + ''.join(
        sorted(ax for ax in axis_labels if counts[ax] == 1))

  return input_axis_labels, output_axis_labels


def _einsum_reduction(t0, t0_axis_labels, t1, t1_axis_labels, axes_to_sum):
  """Helper for einsum() that computes the result of a two-argument einsum().

  Args:
    t0: a `Tensor`
    t0_axis_labels: a string of axis labels.  This string's length must equal
      the rank of t0.
    t1: a `Tensor`
    t1_axis_labels: a string to axis labels.  This string's length must equal
      the rank of t1.
    axes_to_sum: set of labels of axes to be summed over

  Returns:
    A `Tensor` whose elements are obtained by summing, over all axes in
    `axes_to_sum`, the corresponding elements of `t0` and `t1`.

    For example, if t0_axis_labels == 'abijk', t1_axis_labels == 'acjkl', and
    axes_to_sum == {j,k}, this will return a tensor x where

      out[a,b,c,i,l] = sum_j sum_k t0[a,b,i,j,k] * t1[a,c,j,k,l]

  Raises:
    ValueError: if the rank of `t0` does not match the length of
      `t0_axis_labels`, or that of `t1` does not match the length of
      `t1_axis_labels`.
  """
  if len(t0_axis_labels) != len(t0.get_shape()):
    raise ValueError(
        'Tensor t0 of rank %d does not match einsum reduction of length %d' %
        (len(t0.get_shape()), len(t0_axis_labels)))
  if len(t1_axis_labels) != len(t1.get_shape()):
    raise ValueError(
        'Tensor t1 of rank %d does not match einsum reduction of length %d' %
        (len(t1.get_shape()), len(t1_axis_labels)))

  # This function computes the result of a two-argument einsum() using batch
  # matrix multiplication.  This involves
  # 1. transposing t0 and t1 so that axes are in the correct order for
  #    batch matrix multiplication, and
  # 2. reshaping t0 and t1 so that they are both of rank 3.

  # First, we divide axes into three groups:
  #  * "preserved" axes are present in both inputs and the output
  #  * "summed" axes are present in both inputs but not the output
  #  * "broadcast" axes are present in exactly one input and the output
  #
  # As an example, if the einsum is abijk,acjkl->abcil, then "a" is a
  # preserved axis, "b" and "c" are broadcast axes, and "j" and "k" are
  # summed axes.
  assert all(a in t0_axis_labels and a in t1_axis_labels for a in axes_to_sum)
  preserved_axes = (set(t0_axis_labels) & set(t1_axis_labels)) - axes_to_sum
  broadcast_axes = {}
  for i, sym_list in enumerate([t0_axis_labels, t1_axis_labels]):
    broadcast_axes[i] = set(sym_list) - preserved_axes - axes_to_sum

  # Reorder the axes so that:
  # 1. preserved axes come first in both inputs
  # 2. in input 0, broadcast axes come next, followed by summed axes
  # 3. in input 1, summed axes come next, followed by broadcast axes
  def sort_key(input_index, a):
    if a in preserved_axes:
      return (-1, a)
    elif ((input_index == 0 and a in broadcast_axes[0]) or
          (input_index == 1 and a in axes_to_sum)):
      return (0, a)
    else:
      return (1, a)

  axis_labels = [t0_axis_labels, t1_axis_labels]
  sorted_axes = [
      sorted(sym_list, key=lambda a: sort_key(i, a))
      for i, sym_list in enumerate(axis_labels)
  ]
  inputs = [t0, t1]
  for i, axes_str in enumerate(axis_labels):
    perm = [axes_str.find(a) for a in sorted_axes[i]]
    inputs[i] = _transpose_if_necessary(inputs[i], perm)
  t0, t1 = inputs

  if not axes_to_sum:
    # In the special case where there are no axes to sum over, reduce to mul()
    # rather than to batch matrix multiplication.
    for _ in broadcast_axes[1]:
      t0 = array_ops.expand_dims(t0, -1)
    for _ in broadcast_axes[0]:
      t1 = array_ops.expand_dims(t1, len(preserved_axes))
    product = math_ops.multiply(t0, t1)
    product_axes = sorted_axes[0] + sorted_axes[1][len(preserved_axes):]
    return product, ''.join(product_axes)
  else:
    # Reduce to matmul().

    # Reshape both inputs so as to combine multiple broadcast axes
    # into a single axis, and combine multiple summed axes into a
    # single axis.

    t0_shape = _get_shape(t0)
    num_broadcast_elements_t0 = _total_size(
        t0_shape[len(preserved_axes):-len(axes_to_sum)])
    num_summed_elements = _total_size(t0_shape[-len(axes_to_sum):])
    new_shape = (
        t0_shape[:len(preserved_axes)] +
        [num_broadcast_elements_t0, num_summed_elements])
    t0 = _reshape_if_necessary(t0, new_shape)

    t1_shape = _get_shape(t1)
    num_broadcast_elements_t1 = _total_size(
        t1_shape[len(preserved_axes) + len(axes_to_sum):])
    new_shape = (
        t1_shape[:len(preserved_axes)] +
        [num_summed_elements, num_broadcast_elements_t1])
    t1 = _reshape_if_necessary(t1, new_shape)

    product = math_ops.matmul(t0, t1)

    # Undo compaction of broadcast axes
    uncompacted_shape = (
        t0_shape[:len(preserved_axes) + len(broadcast_axes[0])] +
        t1_shape[len(t1_shape) - len(broadcast_axes[1]):])
    product = _reshape_if_necessary(product, uncompacted_shape)

    product_axes = (
        sorted_axes[0][:len(preserved_axes) + len(broadcast_axes[0])] +
        sorted_axes[1][len(sorted_axes[1]) - len(broadcast_axes[1]):])

    return product, ''.join(product_axes)


def _transpose_if_necessary(tensor, perm):
  """Like transpose(), but avoids creating a new tensor if possible."""
  if perm != range(len(perm)):
    return array_ops.transpose(tensor, perm=perm)
  else:
    return tensor


def _reshape_if_necessary(tensor, new_shape):
  """Like reshape(), but avoids creating a new tensor if possible."""
  # Accept None as an alias for -1 in new_shape.
  new_shape = tuple(-1 if x is None else x for x in new_shape)
  cur_shape = tuple(x.value for x in tensor.get_shape().dims)
  if (len(new_shape) == len(cur_shape) and
      all(d0 == d1 or d1 == -1 for d0, d1 in zip(cur_shape, new_shape))):
    return tensor
  else:
    return array_ops.reshape(tensor, new_shape)


def _get_shape(tensor):
  """Like get_shape().as_list(), but explicitly queries the shape of a tensor
  if necessary to ensure that the returned value contains no unknown value."""

  shape = tensor.get_shape().as_list()
  none_indices = [i for i, d in enumerate(shape) if d is None]
  if none_indices:
    # Query the shape if shape contains None values
    shape_tensor = array_ops.shape(tensor)
    for i in none_indices:
      shape[i] = shape_tensor[i]
  return shape


def _total_size(shape_values):
  """Given list of tensor shape values, returns total size.
  If shape_values contains tensor values (which are results of
  array_ops.shape), then it returns a scalar tensor.
  If not, it returns an integer."""

  result = 1
  for val in shape_values:
    result *= val
  return result



def _einsum_optimize_dp(ishapes, ilabels, olabels, cost_limit=np.inf):
  # decompose the contraction graph into connected subgraphs and optimise
  # each subgraph using _einsum_optimize_dp_connected
  c = [
    _einsum_optimize_dp_connected(
      [ishapes[j] for j in g], 
      [ilabels[j] for j in g], 
      olabels, cost_limit, g
    ) for g in _find_subgraphs(ilabels, olabels)
  ]
  return _tree_to_sequence(reduce(lambda c1, c2: (c1, c2), c))


def _find_subgraphs(ilabels, olabels):
  subgraphs = []
  unused = set(range(len(ilabels)))
  
  while len(unused) > 0:
    g = []
    q = [unused.pop()]
    while len(q) > 0:
      x = q.pop(0)
      g.append(x)
      n = {
        y for y in unused 
        if len((set(ilabels[x]) & set(ilabels[y])) - set(olabels)) > 0
      }
      q.extend(n)
      unused -= n
    
    subgraphs.append(g)
    
  return subgraphs


def _einsum_optimize_dp_connected(ishapes, ilabels, olabels, 
                                  cost_limit=np.inf, tensor_indices=None):
                                  
  # find an optimal contraction using breadth-first search with dynamic 
  # programming but ignoring solutions with intermediate outer products
  # and solutions with contraction cost larger than cost_limit
  
  n = len(ishapes)
  if tensor_indices is None: 
    tensor_indices = list(range(n))
  x = [
    None, # just ignore x[0]
    {
      frozenset([j]): (ishapes[j], ilabels[j], 0, tensor_indices[j]) 
      for j in range(n)
    }
  ]
  # x[n_tensors][set of tensors] = (shape, labels, cost, contraction)
  
  for m in range(2, n+1): # construct x[m]
    x.append(dict())
    
    for k in range(1, m//2+1): # try to combine all x[m-k] and x[k]
    
      for s1 in x[m-k]:
        d1, l1, c1, e1 = x[m-k][s1]
        
        for s2 in x[k]:
          if len(s1 & s2) == 0:
            d2, l2, c2, e2 = x[k][s2]
            
            s = s1 | s2
            
            common_indices = set(l1) & set(l2)
            contraction_indices = common_indices - set(olabels)
            
            if len(contraction_indices) > 0: # ignore outer products

              # m1[l] <-- is l1[l] an index of the new tensor? (m2 for l2)
              m1 = [l not in contraction_indices for l in l1]
              m2 = [l not in common_indices      for l in l2]

              new_shape = tuple(
                [d for d, f in zip(d1, m1) if f] + \
                [d for d, f in zip(d2, m2) if f]
              )

              new_labels = \
                ''.join([l for l, f in zip(l1, m1) if f]) + \
                ''.join([l for l, f in zip(l2, m2) if f])
              
              contraction_cost = np.prod(d1) * \
                                 np.prod([d for d, f in zip(d2, m2) if f])
              total_cost = contraction_cost + c1 + c2
              
              if s not in x[m] or total_cost < min(x[m][s][2], cost_limit):
                x[m][s] = (new_shape, new_labels, total_cost, (e1, e2))

  return x[n][list(x[n].keys())[0]][3]


def _tree_to_sequence(contraction):
  # converts a contraction tree to a contraction sequence, e.g.
  # ((0,1),(2,(3,4))) --> [(0, 1), (2, 3), (0, 2), (0, 1)]
  
  if type(contraction) == int:
    return []
  
  t1 = [contraction]
  t2 = []
  seq = []
  
  while len(t1) > 0:
    x = t1.pop(0)
    assert type(x) == tuple and len(x) == 2
    t1_new = [t for t in x if type(t) == tuple][::-1]
    t2_new = [t for t in x if type(t) == int]
    assert len(t1_new) + len(t2_new) == 2
    
    t1 = t1_new + t1
    seq_new = tuple(range(len(t1_new)))
    
    for t in sorted(t2_new):
      p = max([0] + [j+1 for j,n in enumerate(t2) if n < t])
      t2.insert(p, t)
      seq_new += (p + len(t1),)
    
    seq.insert(0, seq_new)

  return seq


def _einsum_optimize_greedy(ishapes, ilabels, olabels):
  
  ishapes = list(ishapes)
  ilabels = list(ilabels)
  seq = []
  
  total_cost = 0
  
  while len(ishapes) > 1:
    min_cost = np.inf
    cheapest_contraction = None
    
    for j in range(len(ilabels)-1):
      l1, d1 = ilabels[j], ishapes[j]
      for k in range(j+1, len(ilabels)):
        l2, d2 = ilabels[k], ishapes[k]
        
        common_indices = set(l1) & set(l2)
        contraction_indices = common_indices - set(olabels)
        
        # m1[l] <-- is l1[l] an index of the new tensor? (m2 for l2)
        m1 = [l not in contraction_indices for l in l1]
        m2 = [l not in common_indices      for l in l2]
        
        new_shape = tuple(
          [d for d, f in zip(d1, m1) if f] + \
          [d for d, f in zip(d2, m2) if f]
        )

        new_labels = \
          ''.join([l for l, f in zip(l1, m1) if f]) + \
          ''.join([l for l, f in zip(l2, m2) if f])
        
        cost = np.prod(d1) * \
               np.prod([d for d, f in zip(d2, m2) if f])
        
        if cost < min_cost:
          min_cost = cost
          cheapest_contraction = (j, k, new_shape, new_labels)
    
    j, k, d, l = cheapest_contraction
    seq.append((j,k))
    ishapes.pop(k)
    ishapes.pop(j)
    ishapes.insert(0, d)
    ilabels.pop(k)
    ilabels.pop(j)
    ilabels.insert(0, l)
    
    total_cost += min_cost
    
  return seq


def _exponential_space_einsum(equation, *inputs):
  """Fallback implementation that supports summing an index over > 2 inputs."""
  inputs = list(inputs)
  input_shapes = [x.get_shape() for x in inputs]
  idx_in, idx_out = _einsum_parse_and_resolve_equation(equation, input_shapes)

  idx_all = set(''.join(idx_in) + idx_out)
  indices = ''.join(sorted(idx_all))

  missing_idx = set(idx_out).difference(idx_all)
  if missing_idx:
    raise ValueError('Unknown output axes: %s' % missing_idx)

  axis_order = {}
  for ax in indices:
    if ax not in idx_out:
      axis_order[ax] = len(axis_order)
  for ax in idx_out:
    axis_order[ax] = len(axis_order)

  # transpose inputs so axes are in order
  for i, (input_, axes_) in enumerate(zip(inputs, idx_in)):
    if input_.get_shape().ndims != len(axes_):
      raise ValueError(
          'Input %d with axes %s has incorrect' \
          ' number of dimensions (expected %d, got %d)' % (
              i, axes_, len(axes_), input_.get_shape().ndims
          )
      )

    sorted_idx = sorted(axes_, key=axis_order.get)

    if len(set(axes_)) != len(axes_):
      raise ValueError(
          'Subscript not supported: an axis appears more than once: %s' % axes_)

    if list(axes_) != sorted_idx:
      permuted = [axes_.find(ax) for ax in sorted_idx]
      inputs[i] = array_ops.transpose(input_, permuted)
      idx_in[i] = sorted_idx

  reduction_idx = []
  shapes = [[dim if dim else -1
             for dim in tensor.get_shape().as_list()]
            for tensor in inputs]

  # validate shapes for broadcasting
  for j, ax in enumerate(sorted(idx_all, key=axis_order.get)):
    dims = []
    for i, idx in enumerate(idx_in):
      if ax not in idx:
        shapes[i].insert(j, 1)
      else:
        dim = shapes[i][j]
        if isinstance(dim, int) and dim > 1:
          dims.append(dim)

    if len(set(dims)) > 1:
      raise ValueError('Dimension mismatch on axis: %s' % ax)

    if ax not in idx_out:
      reduction_idx.append(j)

  # reshape, multiply
  expanded_inputs = [
      array_ops.reshape(input_, shape) for input_, shape in zip(inputs, shapes)
  ]
  expanded_output = 1
  for input_ in expanded_inputs:
    expanded_output *= input_

  # contract
  return math_ops.reduce_sum(expanded_output, reduction_idx)
