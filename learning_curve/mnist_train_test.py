#############################################################
# ENVIRONMENT
#############################################################

import matplotlib
matplotlib.use('Agg')

# Location of Caffe and logging files and database
caffe_root = "$CAFFE_ROOT/"
caffe_path = "build/tools/caffe"
log_path = "logs/"
fig_path = "imgs/"
db_path = "../mnist/"

# Import necessary modules
import os
import sys
import subprocess
import logging
import time, datetime

# Setting log environment variables before importing caffe
use_python = True
os.environ["GLOG_minloglevel"] = "0"
if use_python:
    os.environ["GLOG_logtostderr"] = "1" # only if using custom log
else:
    os.environ["GLOG_log_dir"] = log_path # only if using glog

# python and caffe
import numpy as np
import matplotlib.pyplot as plt
import caffe
from caffe import layers as L, params as P
from caffe.proto import caffe_pb2

# nideep
from nideep.eval.learning_curve import LearningCurve
from nideep.eval.eval_utils import Phase
import nideep.eval.log_utils as lu

#############################################################
# DATA
#############################################################

# Data already converted to lmdb

def get_locations(prefix_net):
    """
    Relative location of train/test networks and solver
    """
    train_net_path = "prototxt/"+prefix_net+"_train.prototxt"
    test_net_path = "prototxt/"+prefix_net+"_test.prototxt"
    solver_config_path = "prototxt/"+prefix_net+"_solver.prototxt"
    return train_net_path, test_net_path, solver_config_path


#############################################################
# ARCHITECTURE
#############################################################

# INPUT -> FC -> FC -> SIGMOID
def net0(lmdb, batch_size):
    """
    Network 0: oversimplified architecture
    """
    n = caffe.NetSpec()
    n.data, n.label = L.Data(batch_size=batch_size, backend=P.Data.LMDB, source=lmdb,
                             transform_param=dict(scale=1./255), ntop=2)
    n.fc1 = L.InnerProduct(n.data, num_output=50, weight_filler=dict(type='xavier'))
    n.sig1 = L.Sigmoid(n.fc1)
    n.fc2 = L.InnerProduct(n.sig1, num_output=50, weight_filler=dict(type='xavier'))
    n.sig2 = L.Sigmoid(n.fc2)
    n.score = L.InnerProduct(n.sig2, num_output=10, weight_filler=dict(type='xavier'))
    n.accuracy = L.Accuracy(n.score, n.label, include=[dict(phase=caffe.TEST)])
    n.loss = L.SoftmaxWithLoss(n.score, n.label)
    return n.to_proto()

# INPUT -> CONV -> RELU -> FC
def net1(lmdb, batch_size):
    """
    Network 1: standard architecture
    """
    n = caffe.NetSpec()
    n.data, n.label = L.Data(batch_size=batch_size, backend=P.Data.LMDB, source=lmdb,
                             transform_param=dict(scale=1./255), ntop=2)
    n.conv1 = L.Convolution(n.data, kernel_size=5, num_output=50, weight_filler=dict(type='xavier'))
    n.relu1 = L.ReLU(n.conv1, in_place=True)
    n.fc1 = L.InnerProduct(n.relu1, num_output=500, weight_filler=dict(type='xavier'))
    n.score = L.InnerProduct(n.fc1, num_output=10, weight_filler=dict(type='xavier'))
    n.accuracy = L.Accuracy(n.score, n.label, include=[dict(phase=caffe.TEST)])
    n.loss = L.SoftmaxWithLoss(n.score, n.label)
    return n.to_proto()

# INPUT -> [CONV -> POOL -> RELU]*2 -> FC -> RELU -> FC
def net2(lmdb, batch_size):
    """
    Network 2: overcomplicated architecture
    """
    n = caffe.NetSpec()
    n.data, n.label = L.Data(batch_size=batch_size, backend=P.Data.LMDB, source=lmdb,
                             transform_param=dict(scale=1./255), ntop=2)
    n.conv1 = L.Convolution(n.data, kernel_size=5, num_output=50, weight_filler=dict(type='xavier'))
    n.pool1 = L.Pooling(n.conv1, kernel_size=2, stride=2, pool=P.Pooling.MAX)
    n.relu1 = L.ReLU(n.pool1, in_place=True)
    n.conv2 = L.Convolution(n.relu1, kernel_size=5, num_output=50, weight_filler=dict(type='xavier'))
    n.pool2 = L.Pooling(n.conv2, kernel_size=2, stride=2, pool=P.Pooling.MAX)
    n.relu2 = L.ReLU(n.pool2, in_place=True)
    n.fc1 =   L.InnerProduct(n.relu2, num_output=500, weight_filler=dict(type='xavier'))
    n.score =   L.InnerProduct(n.fc1, num_output=10, weight_filler=dict(type='xavier'))
    n.accuracy = L.Accuracy(n.score, n.label, include=[dict(phase=caffe.TEST)])
    n.loss =  L.SoftmaxWithLoss(n.score, n.label)
    return n.to_proto()


#############################################################
# TRAIN/TEST/SOLVE
#############################################################

def make_train_test(net, train_net_path, fpath_train_db, test_net_path, fpath_test_db):
    """
    Write train/test files from python to protocol buffers
    """
    with open(train_net_path, 'w') as f:
        f.write(str(net(fpath_train_db, 64)))

    with open(test_net_path, 'w') as f:
        f.write(str(net(fpath_test_db, 100)))

def make_solver(s, net_prefix, train_net_path, test_net_path, solver_config_path):
    """
    Standard solver for net1
    """
    # Randomization in training
    s.random_seed = 0xCAFFE
    # Locations of the train/test networks
    s.train_net = train_net_path
    s.test_net.append(test_net_path)
    s.test_interval = 100  # Test after every 'test_interval' training iterations.
    s.test_iter.append(100) # Test on 'test_iter' batches each time we test.
    s.max_iter = 10000 # Max training iterations
    # Type of solver
    s.type = "Nesterov" # "SGD", "Adam", and "Nesterov"
    # Initial learning rate and momentum
    s.base_lr = 0.01
    s.momentum = 0.9
    s.weight_decay = 5e-4
    # Learning rate changes
    s.lr_policy = 'inv'
    s.gamma = 0.0001
    s.power = 0.75
    # Display current training loss and accuracy every 10 iterations
    s.display = 10
    # Use GPU to train
    s.solver_mode = caffe_pb2.SolverParameter.GPU
    # Snapshots
    s.snapshot = 5000
    s.snapshot_prefix = "snapshots/" + net_prefix + "_snapshot"
    # Write the solver to a temporary file and return its filename
    with open(solver_config_path, "w") as f:
        f.write(str(s))

def train_test_net_command(solver_config_path):
    """
    Train/test process launching cpp solver from shell.
    """
    # Load solver
    solver = None
    solver = caffe.get_solver(solver_config_path)

    # Launch training command
    command = "{caffe} train -solver {solver}".format(caffe=caffe_root + caffe_path,
                                                      solver=solver_config_path)
    subprocess.call(command, shell=True)

def train_test_net_python(solver_path, log_path, accuracy=False, print_every=100, debug=False):
    """
    Pythonic alternative to train/test a network:
    it captures stderr and logs it to a custom log file.

    Errors in C can't be seen in python, so use subprocess.call
    to see if the script terminated.

	solver_path		- str - Path to the solver's prototxt.
	log_path		- str - Path to the log file.
	accuracy		- boolean - Compute accuracy?
	print_every		- int - Prints indications to the command line every print_every iteration.
	debug			- boolean - Activate debugging? If True, log won't be captured.
    """
    from sklearn.metrics import recall_score, accuracy_score
    start_time = time.time()
    out = start_output(debug, init=True)
    # Get useful parameters from prototxts
    max_iter = get_prototxt_parameter("max_iter", solver_path)
    test_interval = get_prototxt_parameter("test_interval", solver_path)
    # Work on GPU and load solver
    caffe.set_device(0)
    caffe.set_mode_gpu()
    solver = None
    solver = caffe.get_solver(solver_path)
    # Log solving
    log_entry(debug, out, "Solving")

    for it in range(max_iter):
        # Iterate
        solver.step(1)

        # Regularly compute accuracy on test set
        if accuracy:
            if it % test_interval == 0:
                solver.test_nets[0].forward()
                # retrieve labels and predictions
                y_true = solver.test_nets[0].blobs['label'].data
                y_prob = solver.test_nets[0].blobs['score'].data
                # reshape labels and predictions
                y_true = np.squeeze(y_true)
                y_prob = np.squeeze(y_prob)
                if y_true.ndim == 1:
                    n = y_true.shape[0]
                    y_true.reshape(1, n)
                    y_prob.reshape(1, n)
                y_pred = np.array([[prob>=0.5 for prob in preds] for preds in y_prob])
                value_accuracy = accuracy_score(y_true, y_pred)
                #value_accuracy = recall_score(y_true, y_pred, average='macro')
                log_entry(debug, out, "Test net output #1: accuracy = {}".format(value_accuracy))

        # Regularly print iteration
        if it % print_every == 0:
            print "Iteration", it

        # Regularly purge stderr/output grabber
        if it % 1000 == 0:
            out = purge_output(debug, out, log_path)
    # Break output stream and write to log
    stop_output(debug, out, log_path)
    pass


#############################################################
# LEARNING CURVE
#############################################################

from pylab import rcParams
rcParams['figure.figsize'] = 16, 6
rcParams.update({'font.size': 15})

def print_learning_curve(net_prefix, log_path, fig_path, accuracy=True):
    """
    Print learning curve inline (for jupiter notebook) or by saving it
    """
    e = LearningCurve(log_path)
    e.parse()

    for phase in [Phase.TRAIN, Phase.TEST]:
        num_iter = e.list('NumIters', phase)
        loss = e.list('loss', phase)
        plt.plot(num_iter, loss, label='on %s set' % (phase.lower(),))

        plt.xlabel('iteration')
        # format x-axis ticks
        ticks, _ = plt.xticks()
        plt.xticks(ticks, ["%dK" % int(t/1000) for t in ticks])
        plt.ylabel('loss')
        plt.title(net_prefix+' on train and test sets')
        plt.legend()
    plt.grid()
    plt.savefig(fig_path + net_prefix + "_learning_curve.png")

    if accuracy:
        plt.figure()
        num_iter = e.list('NumIters', phase)
        acc = e.list('accuracy', phase)
        plt.plot(num_iter, acc, label=e.name())

        plt.xlabel('iteration')
        plt.ylabel('accuracy')
        plt.title(net_prefix+" on %s set" % (phase.lower(),))
        plt.legend(loc='lower right')
        plt.grid()
        plt.savefig(fig_path + net_prefix + "_accuracy.png")


#############################################################
# UTILS FOR CUSTOM LOGGING
#############################################################

def make_time_stamp(pattern):
    """
    Time stamp with explicit string pattern.
	A possible pattern would be '%Y%m%d_%H%M%S'.
    """
    now = time.time()
    return datetime.datetime.fromtimestamp(now).strftime(pattern)

def log_entry(debug, out, text):
    """
    Standardized log entries for glog
    """
    # Format log entry
    monthday = make_time_stamp('%m%d')
    time_stamp = make_time_stamp('%H:%M:%S')
    now = time.time()
    ms = "."+str('%06d' % int((now - int(now)) * 1000000))
    line_form = "I{monthday} {time_stamp}  0000 main.py:00] {text}\n"
    entry = line_form.format(monthday=monthday, time_stamp=time_stamp+ms, text=text)

    # Log entry to out
    write_output(debug, out, entry)
    pass

def get_prototxt_parameter(param, prototxt):
    with open(prototxt) as f:
        try:
            line = [s for s in f.readlines() if param in s][-1]
            param_value = int(line.rstrip().split(": ")[1].split("#")[0])
        except IndexError:
            print "{} not defined in prototxt {} or bad layout.".format(param, prototxt)
    return param_value


#############################################################
# WRITE TO LOG: log without glog which works poorly in python
#############################################################

import os
import sys

def start_output(debug, init=False):
    """
    Start stderr grabber
    """
    if not debug:
        out = OutputGrabber()
        out.start(init)
        return out
    return None

def write_output(debug, out, entry):
    if not debug:
        out.write(entry)
    pass

def purge_output(debug, out, log_path):
    """
    Stop and start stderr grabber in the same log file
    """
    if not debug:
        stop_output(debug, out, log_path)
        new_out = start_output(debug)
        return new_out
    return None

def stop_output(debug, out, log_path):
    """
    Stop stderr grabber and close files
    """
    if not debug:
        out.stop(log_path)
    pass

class OutputGrabber(object):
    """
    Class used to grab stderr (default) or another stream
    """
    escape_char = "\b"

    def __init__(self, stream=sys.stderr):
        self.origstream = stream
        self.origstreamfd = self.origstream.fileno()
        self.capturedtext = ""
        # Create a pipe so the stream can be captured
        self.pipe_out, self.pipe_in = os.pipe()
        pass

    def start(self, init=False):
        """
        Start capturing the stream data
        """
        self.capturedtext = ""
        # Save a copy of the stream
        self.streamfd = os.dup(self.origstreamfd)
        # Replace the original stream with our write pipe
        os.dup2(self.pipe_in, self.origstreamfd)
        # Patch log file with time stamp on first line if initialization
        if init:
            time_stamp = make_time_stamp('%Y/%m/%d %H-%M-%S')
            log_beginning = "Log file created at: {}\n".format(time_stamp)
            self.origstream.write(log_beginning)
        pass

    def write(self, entry):
        self.origstream.write(entry)
        pass

    def stop(self, filename):
        """
        Stop capturing the stream data and save the text in `capturedtext`
        """
        # Flush the stream to make sure all our data goes in before
        # the escape character.
        self.origstream.flush()
        # Print the escape character to make the readOutput method stop
        self.origstream.write(self.escape_char)
        self.readOutput()
        # Close the pipe
        os.close(self.pipe_out)
        # Restore the original stream
        os.dup2(self.streamfd, self.origstreamfd)
        # Write to file filename
        f = open(filename, "a")
        f.write(self.capturedtext)
        f.close()
        pass

    def readOutput(self):
        """
        Read the stream data (one byte at a time)
        and save the text in `capturedtext`
        """
        while True:
            data = os.read(self.pipe_out, 1)  # Read One Byte Only
            if self.escape_char in data:
                break
            if not data:
                break
            self.capturedtext += data
        pass


#############################################################
# MAIN
#############################################################

if __name__ == "__main__":

    nets = [(net0, "net0"),
            (net1, "net1"),
            (net2, "net2")]

    # Time stamp
    time_stamp = make_time_stamp('%Y%m%d_%H%M%S')

    # Path to lmdb
    fpath_train_db = db_path+"mnist_train_lmdb"
    fpath_test_db = db_path+"mnist_test_lmdb"

    for (net, net_prefix) in nets:
        # Log/fig names with time stamp
        process_name = net_prefix + "_" + time_stamp
        log_path = log_path + "caffe_" + process_name + ".log"
        fig_name = fig_path + process_name + ".png"
        print "Training process:", process_name

        # New cpp solver for each net
        s = caffe_pb2.SolverParameter()

        # Make prototxts
        train_net_path, test_net_path, solver_config_path = get_locations(net_prefix)
        make_train_test(net, train_net_path, fpath_train_db, test_net_path, fpath_test_db)
        make_solver(s, net_prefix, train_net_path, test_net_path, solver_config_path)

        # Solve neural net and write to log (uncomment command or python)
        # train_test_net_command_command(solver_config_path)
        train_test_net_python(solver_config_path, 1000, log_path, accuracy=False)
