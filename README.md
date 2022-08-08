# Marie-ICR

Integrate AI-powered OCR features into your applications

## Installation

create folder structure

```sh 
mkdir models config
```

Follow instructions from `pytorch` website

```sh
https://pytorch.org/get-started/locally/
```

Install required packages with `pip`

```sh
$ pip install -r ./requirements/requirements.txt
```

Build Docker Image

```sh
DOCKER_BUILDKIT=1 docker build . -t marie-icr:1.3
```

```sh
DOCKER_BUILDKIT=1 docker build . -f Dockerfile -t gregbugaj/marie-icr:2.3-cuda --no-cache  && docker push gregbugaj/marie-icr:2.3-cuda
docker push gregbugaj/marie-icr:2.3-cuda

DOCKER_BUILDKIT=1 docker build . -f Dockerfile -t gregbugaj/marie-icr:2.3-cuda --no-cache  && docker push gregbugaj/marie-icr:2.3-cuda
docker push gregbugaj/marie-icr:2.3-cuda
```


docker stop $(docker ps -q)
docker rmi -f $(docker images -aq)
docker logs  marie-icr-0  -f --since 0m

docker container stop $(docker container ls -aq) && docker system prune -af --volumes


cd ~/dev/marie-ai/docker-util/ && docker container stop $(docker container ls -q --filter name='marie*') && ./update.sh && ./run-all.sh
cd ~/dev/marie-ai/docker-util/ && docker container stop $(docker container ls -q --filter name='marie*') && ./update.sh && ./run-all.sh
docker container stop $(docker container ls -q --filter name='marie*')

-v `pwd`/../cache:/opt/marie-icr/.cache:rw \

Starting in Development mode

```sh
 PYTHONPATH="$PWD" python ./marie/app.py
``

Enable encryption 

```sh
python ./app.py --enable-crypto  --tls-cert ./cert.pem
```


Starting in Production mode with `gunicorn`. Config
[gunicorn]settings (https://docs.gunicorn.org/en/stable/settings.html#settings)

```sh
gunicorn -c gunicorn.conf.py wsgi:app  --log-level=debug
```

Activate the environment as we used `PIP` to install `docker-compose` (python -m pip install docker-compose)

```sh
    source  ~/environments/pytorch/bin/activate
```

## Docker 

### CPU
Building docker container 

```sh
# --no-cache
DOCKER_BUILDKIT=1 docker build . -f Dockerfile -t marie-icr:2.0 --network=host --no-cache
```

### GPU

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

```sh
DOCKER_BUILDKIT=1 docker build . -f Dockerfile -t marie-icr:2.0 --network=host --no-cache

DOCKER_BUILDKIT=1 docker build . -f Dockerfile -t gregbugaj/marie-icr:2.2-cuda --no-cache && docker push gregbugaj/marie-icr:2.2-cuda
```

### Inference on the gpu
Install following dependencies to ensure docker is setup for GPU processing.

https://docs.nvidia.com/ai-enterprise/deployment-guide/dg-docker.html
https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

Before continuing we need to ensure that our container is configured b
```sh
#### Test nvidia-smi with the latest official CUDA image
docker run --gpus all nvidia/cuda:11.0-base nvidia-smi
docker run --gpus all --shm-size=1g --ulimit memlock=-1 --ulimit stack=67108864  nvidia/cuda:11.0-base nvidia-smi
```

Overwrite the container `ENTRYPOINT` by using `--entrypoint` from command line and validate the GPU works by executing 
`nvidia-smi`

```sh
docker run -it --rm  --gpus all --entrypoint /bin/bash marie-icr:2.0
```




Remove dangling containers

```sh
docker rmi -f $(docker images -f "dangling=true" -q)
```

### Docker compose

Install docker-compose https://www.digitalocean.com/community/tutorials/how-to-install-and-use-docker-compose-on-ubuntu-20-04

```shell
sudo curl -L "https://github.com/docker/compose/releases/download/v2.6.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/bin/docker-compose
sudo chmod +x /usr/bin/docker-compose
docker-compose --version
```

Start docker compose

```sh
DOCKER_BUILDKIT=1 docker-compose up

docker-compose down --volumes --remove-orphans && DOCKER_BUILDKIT=1 docker-compose up -d
```

Cleanup containers

```sh
    docker-compose down --volumes --remove-orphans
```

# Default Ports

8500 -- Consul
5000 -- Traefik - Entrypoint
7777 -- Traefik - Dashboard


# 
```sh
# tests/integration/psql_storage
docker-compose -f docker-compose.yml --project-directory . up  --build  --remove-orphans
```

# Setup Redis
https://hub.docker.com/_/redis
https://redis.io/docs/stack/get-started/install/docker/

```sh
  python -m pip install redis
``


```sh
docker run --name marie_redis -p 6379:6379 -d redis 

docker run --rm --name marie_redis -p 6379:6379 redis 
```

```sh
docker exe -it marie_redis sh
```

## Codestyle / Formatting

```sh

```
## Issues

There is a segmentation fault happening with `opencv-python==4.5.4.62` switching to `opencv-python==4.5.4.60` fixes the issue. 
[connectedComponentsWithStats produces a segfault ](https://github.com/opencv/opencv-python/issues/604)
```
pip install opencv-python==4.5.4.60
```

## References

[consul-catalog](https://doc.traefik.io/traefik/v2.2/providers/consul-catalog/)
[apispec](https://apispec.readthedocs.io/en/latest/install.html)
[gradio](https://gradio.app/)
[deepdoctection](https://github.com/deepdoctection/deepdoctection)
[Consul / Traefik configuration](https://devonhubner.org/using_traefik_with_consul/)
https://github.com/Lightning-AI

## Implement models

## Stream processing
[KSQL Stream processing example ](https://www.confluent.io/blog/sysmon-security-event-processing-real-time-ksql-helk/)
[KSQL](https://pypi.org/project/ksql/)
 

## Research 
[table-transformer](https://github.com/microsoft/table-transformer)
[DocumentUnderstanding](https://github.com/bikash/DocumentUnderstanding)
[DocumentAI] (https://www.microsoft.com/en-us/research/project/document-ai/)

Implement secondary box detection method.
[TextFuseNet](TextFuseNethttps://github.com/ying09/TextFuseNet)
Implement DocFormer: End-to-End Transformer for Document Understanding
[DocFormer_End-to-End_Transforme](https://openaccess.thecvf.com/content/ICCV2021/papers/Appalaraju_DocFormer_End-to-End_Transformer_for_Document_Understanding_ICCV_2021_paper.pdf)

## 
Install `fairseq` from source, the release version is  missing `convert_namespace_to_omegaconf`

```sh
git clone https://github.com/pytorch/fairseq.git
cd fairseq
pip install -r requirements.txt
python setup.py build develop
```

https://github.com/ShannonAI/service-streamer
https://github.com/NVIDIA/apex
https://github.com/pytorch/fairseq
https://discuss.pytorch.org/t/cnn-fp16-slower-than-fp32-on-tesla-p100/12146/7
https://discuss.pytorch.org/t/torch-cuda-amp-inferencing-slower-than-normal/123684

Fix issue 
```
AttributeError: module 'distutils' has no attribute 'version'
```

```
python3 -m pip install setuptools==59.5.0
```



[//]: # (https://mmocr.readthedocs.io/en/latest/)
[//]: # (https://github.com/anibali/docker-pytorch)
[//]: # (https://github.com/AleksK1NG/Go-Kafka-gRPC-MongoDB-microservice/blob/master/docker-compose.yml)


ImageMagic 6 policy
```sh
/etc/ImageMagick-6/policy.xml
```

## Download assets locally
Load gpt2 dictionary from https://layoutlm.blob.core.windows.net/trocr/dictionaries/gpt2_with_mask.dict.txt



## Models to implement
https://github.com/ibm-aur-nlp/PubLayNet

DocFormer: End-to-End Transformer for Document Understanding

## Credits

This application uses Open Source components. You can find the source code of their open source projects along with license information in the NOTICE. 
We acknowledge and are grateful to these developers for their contributions to open source.


https://github.com/alibaba/EasyNLP?ref=stackshare
https://huggingface.co/spaces/rajistics/receipt_extractor/blob/main/app.py
https://github.com/UBIAI/layoutlmv3FineTuning/blob/master/Layoutlmv3_inference/inference_handler.py
https://powerusers.microsoft.com/t5/AI-Builder/bd-p/AIBuilder
https://github.com/NielsRogge/Transformers-Tutorials/blob/master/LayoutLMv2/FUNSD/True_inference_with_LayoutLMv2ForTokenClassification_%2B_Gradio_demo.ipynb


## Datastore
https://github.com/allenai/datastore

# GRPC
https://docs.microsoft.com/en-us/aspnet/core/grpc/test-tools?view=aspnetcore-6.0