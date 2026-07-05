## Data Analysis Package for KELpie - Real-Time Plotting (DAPKEL_RTP)

Package with an application for data acquisition and real-time plotting of sensor population for the Kelpie detector. 

<!-- ![Tests](https://github.com/rngKomorebi/LinoSPAD2/actions/workflows/tests.yml/badge.svg)
![Documentation](https://github.com/rngKomorebi/LinoSPAD2/actions/workflows/documentation.yml/badge.svg)
![PyPI - Version](https://img.shields.io/pypi/v/daplis)
![PyPI - License](https://img.shields.io/pypi/l/daplis) -->

## Introduction

The Kelpie detector was developed at EPFL by Dr. Tommaso Milanese. It features a 64x64 Single-Photon Avalanche Device (SPAD) sensor with a 2x2 macropixel building block. It is fully reprogrammable, with high PDE across whole visible spectrum with a peak at 780 nm, 40 ps (rms) jitter, low dark count rate (DCR) and reasonable cross-talk.

This package was derived from the original functions written in Matlab by Dr. Milanese for starting the data acquisition and real-time plotting of the camera's hitmap

## Structure of the package

The "functions" folder holds all functions from unpacking to plotting numerous types of graphs (pixel population, histograms of timestamp differences, etc.)

The "gui" folder hold python code for the app itself including the contents of each tab.

The "params" tab hold the programs for programming the SPADs and the bitfile data for communicating with the camera.

The standalone repo for the offline data unpacking and analysis can be found [here](https://github.com/rngKomorebi/dapkel).

## Installation and usage

A fresh, separate virtual environment is highly recommended before installing the package.
This can be done using pip, see, e.g., [this](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/).
This can help to avoid any dependency conflicts and ensure smooth operation of the
package.

First, check if the virtualenv package is installed. To do this, one can run:
```
pip show virtualenv
```
If the package was not found, it can be installed using:
```
pip install virtualenv
```
To create a new environment, run the following:
```
virtualenv PATH/TO/NEW/ENVIRONMENT
```
To activate the environment (on Windows):
```
PATH/TO/NEW/ENVIRONMENT/Scripts/activate
```
and on Linux:
```
source PATH/TO/NEW/ENVIRONMENT/bin/activate
```

Alternatively, to start using the package, one can download the whole repo. "requirements.txt" 
lists all packages required for this project to run. One can create 
an environment for this project either using conda or pip following the instruction 
above. Once the new environmnt is activated, run the following to install 
the required packages:
```
cd PATH/TO/GITHUB/CODES/dapkel-rtp
pip install -r requirements.txt
```
Now, the package can be installed via
```
pip install -e .
```
where '-e' stands for editable: any changes introduced to the package will
instantly become a part of the package and can be used without the need
of reinstalling the whole thing.

For conda users, the new environment can be installed using the 'requirements' 
text file directly:
```
conda create --name NEW_ENVIRONMENT_NAME --file /PATH/TO/requirements.txt -c conda-forge
```
To install the package, first, switch to the created environment:
```
conda activate NEW_ENVIRONMENT_NAME
```
and run
```
pip install -e .
```

## How to contribute

This repo consists of two branches: 'main' serves as the release version
of the package, tested, proven to be functional, and ready to use, while
the 'develop' branch serves as the main hub for testing new stuff. To
contribute, the best way would be to fork the repository and use the 'develop'
branch for new introductions, submitting the results via pull requests. 
Everyone willing to contribute is kindly asked to follow the 
[PEP 8](https://peps.python.org/pep-0008/) and 
[PEP 257](https://peps.python.org/pep-0257/) conventions.

## License and contact info

This package is available under the MIT license. See LICENSE for more information. If you'd like to contact me, the author, feel free to write at sergei.kulkov23@gmail.com.
