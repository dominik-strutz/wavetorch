import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

import torch
from torch.utils.data import TensorDataset, random_split, DataLoader
from torch.nn.functional import pad

from wavetorch import *

import argparse
import time

if __name__ == '__main__':
    # Parse command line arguments
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--N_epochs', type=int, default=5)
    argparser.add_argument('--Nx', type=int, default=160)
    argparser.add_argument('--Ny', type=int, default=90)
    argparser.add_argument('--dt', type=float, default=0.707)
    argparser.add_argument('--probe_space', type=int, default=15)
    argparser.add_argument('--probe_x', type=int, default=110)
    argparser.add_argument('--probe_y', type=int, default=30)
    argparser.add_argument('--src_x', type=int, default=40)
    argparser.add_argument('--src_y', type=int, default=45)
    argparser.add_argument('--sr', type=int, default=5000)
    argparser.add_argument('--learning_rate', type=float, default=0.01)
    argparser.add_argument('--ratio_train', type=float, default=0.5)
    argparser.add_argument('--batch_size', type=int, default=10)
    argparser.add_argument('--num_of_each', type=int, default=2)
    argparser.add_argument('--num_threads', type=int, default=4)
    argparser.add_argument('--pad_fact', type=float, default=1.0)
    argparser.add_argument('--use-cuda', action='store_true')
    args = argparser.parse_args()

    torch.set_num_threads(args.num_threads)

    # figure out which device we're on
    if args.use_cuda and torch.cuda.is_available():
        print("Using GPU...")
        args.dev = torch.device('cuda')
    else:
        print("Using CPU...")
        args.dev = torch.device('cpu')

    # Each dir corresponds to a distinct class and is automatically given a corresponding one hot
    directories_str = ("./data/vowels/a/",
                       "./data/vowels/e/",
                       "./data/vowels/o/")

    x, y_labels = load_all_vowels(directories_str, sr=args.sr, normalize=True, num_of_each=args.num_of_each)
    x = pad(x, (1, int(x.shape[1] * args.pad_fact)))
    N_samples, N_classes = y_labels.shape

    x = x.to(args.dev)
    y_labels = y_labels.to(args.dev)

    # Put tensors into Datasets and then Dataloaders to let pytorch manage batching
    full_ds = TensorDataset(x, y_labels)
    train_ds, test_ds = random_split(full_ds, [int(args.ratio_train*N_samples), N_samples-int(args.ratio_train*N_samples)])

    train_dl = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    test_dl = DataLoader(test_ds, batch_size=args.batch_size)

    # Setup probe coords and loss func
    probe_x = args.probe_x
    probe_y = torch.arange(args.probe_y, args.probe_y + N_classes*args.probe_space, args.probe_space)

    criterion = torch.nn.CrossEntropyLoss()

    # Define model
    model = WaveCell(args.dt, args.Nx, args.Ny, args.src_x, args.src_y, probe_x, probe_y, pml_max=3, pml_p=4.0, pml_N=20)
    model.to(args.dev)

    # Define optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)

    # Run training
    print("Using a sample rate of %d Hz (sequence length of %d)" % (args.sr, x.shape[1]))
    print("Using %d total samples (%d of each vowel)" % (len(train_ds)+len(test_ds), args.num_of_each) )
    print("   %d for training" % len(train_ds))
    print("   %d for validation" % len(test_ds))
    print(" --- ")
    print("Now begining training for %d epochs ..." % args.N_epochs)
    t_start = time.time()

    hist_loss_batches = []
    hist_test_acc = []
    hist_train_acc = []

    for epoch in range(1, args.N_epochs + 1):
        t_epoch = time.time()

        loss_batches_ep = []
        test_acc_ep = []
        train_acc_ep = []

        for xb, yb in train_dl:
            # Needed to define this for LBFGS.
            # Technically, Adam doesn't require this but we can be flexible this way
            def closure():
                optimizer.zero_grad()
                loss = criterion(model(xb), yb.argmax(dim=1))
                loss.backward()
                return loss

            # Track loss
            loss = optimizer.step(closure)
            loss_batches_ep.append(loss.item())

            with torch.no_grad():
                model.rho[model.b!=0] = 0.0

            # Track train accuracy
            with torch.no_grad():
                train_acc_ep.append( accuracy(model(xb), yb.argmax(dim=1)) )

        # Track test accuracy
        with torch.no_grad():
            for xb, yb in test_dl:
                test_acc_ep.append( accuracy(model(xb), yb.argmax(dim=1)) )

        # Log metrics
        hist_loss_batches.append(np.mean(loss_batches_ep))
        hist_test_acc.append(np.mean(test_acc_ep))
        hist_train_acc.append(np.mean(train_acc_ep))

        print('Epoch: %2d/%2d   %4.1f sec   |   L = %.3e   accuracy = %.4f (train) / %.4f (test)' % 
                (epoch, args.N_epochs, time.time()-t_epoch, hist_loss_batches[-1], hist_train_acc[-1], hist_test_acc[-1]))

    # Finished training
    print(" --- ")
    print('Total time: %.1f min' % ((time.time()-t_start)/60))
    
    save_model(model)
    
    # Calculate and print confusion matrix
    cm_train, cm_test = calc_cm(model, train_dl, test_dl)

    print("Training CM")
    print(cm_train)

    print("Validation CM")
    print(cm_test)
