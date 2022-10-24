---
sidebar_position: 1
---

# Installation

## Prerequisites
* Linux
* Python 3.8
* Pytorch 1.11.0+cu113  
* CUDA 11.3.1


## Environment Setup

:::note

If you are experienced with PyTorch and have already installed it, just skip this part and jump to the next section. Otherwise, you can follow [these steps](#installation-steps) for the preparation.

:::


##  Using a Python virtual environment

```bash
mkdir ~/marie-ai
cd ~/marie-ai
```


From inside this directory, create a virtual environment using the Python venv module:

```bash
python -m venv .env
```


You can jump in and out of your virtual environment with the activate and deactivate scripts:

```bash
# Activate the virtual environment
source .env/bin/activate

# Deactivate the virtual environment
source .env/bin/deactivate
```

##  Installation Steps

There are number of different ways that this project can be setup.

### From source

If you wish to run and develop `Marie-AI` directly, install it from source:

```

git clone https://github.com/gregbugaj/marie-ai.git
cd marie-ai
git checkout develop

# "-v" increases pip's verbosity.
# "-e" means installing the project in editable mode,
# That is, any local modifications on the code will take effect immediately

pip install -r requirements.txt
pip install -v -e .

```

### If you use Marie-AI as a dependency or third-party package, install it with pip:

```
pip install 'marie-ai>=2.4.0'
```


### Verify the installation

We provide a method to verify the installation via inference demo, depending on your installation method.


```
TODO GRADIO LINK 
```

Also can run the following codes in your Python interpreter:

``` python
  from marie.executor import NerExtractionExecutor
  from marie.utils.image_utils import hash_file

  # setup executor
  models_dir = ("/mnt/data/models/")
  executor = NerExtractionExecutor(models_dir)

  img_path = "/tmp/sample.png"
  checksum = hash_file(img_path)

  # invoke executor
  docs = None
  kwa = {"checksum": checksum, "img_path": img_path}
  results = executor.extract(docs, **kwa)

  print(results)

```


### Install on CPU-only platforms

Marie-AI can be built for CPU-only environment. In CPU mode you can train,  test or inference a model.
However there might be limitations of what operations can be used.


## Docker with GPU Support

### Inference on the gpu
Install following dependencies to ensure docker is setup for GPU processing.

* [Installing Docker and The Docker Utility Engine for NVIDIA GPUs](https://docs.nvidia.com/ai-enterprise/deployment-guide/dg-docker.html)
* [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)


After the installation we can validate the setup with :

[CUDA and cuDNN images from gitlab.com/nvidia/cuda](https://hub.docker.com/r/nvidia/cuda/tags?page=2&ordering=last_updated&name=11.3)


```sh
#### Test nvidia-smi with the official CUDA image
docker run --gpus all nvidia/cuda:11.3.1-runtime-ubuntu20.04 nvidia-smi
docker run --gpus all --shm-size=1g --ulimit memlock=-1 --ulimit stack=67108864 nvidia/cuda:11.3.1-runtime-ubuntu20.04 nvidia-smi
```


### Building container

If we have properly configured our environment you should be able to build the container localy

```sh
DOCKER_BUILDKIT=1 docker build . -f Dockerfile -t gregbugaj/marie-icr:2.4-cuda --no-cache 
docker push gregbugaj/marie-icr:2.4-cuda

```

## Common issues

### Segmentation fault

There is a segmentation fault happening with `opencv-python==4.5.4.62` switching to `opencv-python==4.5.4.60` fixes the issue. 
[connectedComponentsWithStats produces a segfault ](https://github.com/opencv/opencv-python/issues/604)

```
pip install opencv-python==4.5.4.60
```


### Missing convert_namespace_to_omegaconf

Install `fairseq` from source, the release version is  missing `convert_namespace_to_omegaconf`

```bash
git clone https://github.com/pytorch/fairseq.git
cd fairseq
pip install -r requirements.txt
python setup.py build develop
```


### distutils has no attribute version

If you receive following error :

```
AttributeError: module 'distutils' has no attribute 'version'
```

Using following version of `setuptools` will work.

```
python3 -m pip install setuptools==59.5.0
```


### CUDA capability sm_86 is not compatible with the current PyTorch installation

Building GPU version of the framework requires `1.10.2+cu113`. 

If you encounter following error that indicates that we have a wrong version of PyTorch / Cuda

```
1.11.0+cu102
Using device: cuda

/opt/venv/lib/python3.8/site-packages/torch/cuda/__init__.py:145: UserWarning: 
NVIDIA GeForce RTX 3060 Laptop GPU with CUDA capability sm_86 is not compatible with the current PyTorch installation.
The current PyTorch install supports CUDA capabilities sm_37 sm_50 sm_60 sm_70.
If you want to use the NVIDIA GeForce RTX 3060 Laptop GPU GPU with PyTorch, please check the instructions at https://pytorch.org/get-started/locally/

  warnings.warn(incompatible_device_warn.format(device_name, capability, " ".join(arch_list), device_name))

```