---
library_name: transformers
tags:
- vision
license: apache-2.0
pipeline_tag: zero-shot-object-detection
---


# MM Grounding DINO (base variant)

[MM Grounding DINO](https://arxiv.org/abs/2401.02361) model was proposed in [An Open and Comprehensive Pipeline for Unified Object Grounding and Detection](https://arxiv.org/abs/2401.02361) by Xiangyu Zhao, Yicheng Chen, Shilin Xu, Xiangtai Li, Xinjiang Wang, Yining Li, Haian Huang.

MM Grounding DINO improves upon the [Grounding DINO](https://huggingface.co/docs/transformers/model_doc/grounding-dino) by improving the contrastive class head and removing the parameter sharing in the decoder, improving zero-shot detection performance on both COCO (50.6(+2.2) AP) and LVIS (31.9(+11.8) val AP and 41.4(+12.6) minival AP).

You can find all the original MM Grounding DINO checkpoints under the [MM Grounding DINO](https://huggingface.co/collections/rziga/mm-grounding-dino-6839881a7f983113fafdbb0e) collection.


## Intended uses

You can use the raw model for zero-shot object detection.

Here's how to use the model for zero-shot object detection:

```py
import torch
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
from transformers.image_utils import load_image


# Prepare processor and model
model_id = "rziga/mm_grounding_dino_base_all"
device = "cuda" if torch.cuda.is_available() else "cpu"
processor = AutoProcessor.from_pretrained(model_id)
model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)

# Prepare inputs
image_url = "http://images.cocodataset.org/val2017/000000039769.jpg"
image = load_image(image_url)
text_labels = [["a cat", "a remote control"]]
inputs = processor(images=image, text=text_labels, return_tensors="pt").to(device)

# Run inference
with torch.no_grad():
    outputs = model(**inputs)

# Postprocess outputs
results = processor.post_process_grounded_object_detection(
    outputs,
    threshold=0.4,
    target_sizes=[(image.height, image.width)]
)

# Retrieve the first image result
result = results[0]
for box, score, labels in zip(result["boxes"], result["scores"], result["labels"]):
    box = [round(x, 2) for x in box.tolist()]
    print(f"Detected {labels} with confidence {round(score.item(), 3)} at location {box}")
```

## Training Data

This model was trained on:
 - [Objects365v1](https://www.objects365.org/overview.html)
 - [GOLD-G](https://arxiv.org/abs/2104.12763)
 - [V3Det](https://github.com/V3Det/V3Det)
 - [COCO 2017](https://cocodataset.org/#home)
 - [LVIS v1.0](https://www.lvisdataset.org/)
 - [COCO 2014](https://cocodataset.org/#home)
 - [GRIT](https://huggingface.co/datasets/zzliang/GRIT)
 - [RefCOCO](https://arxiv.org/abs/1608.00272)
 - [RefCOCO+](https://arxiv.org/abs/1608.00272)
 - [RefCOCOg](https://arxiv.org/abs/1511.02283)
 - [gRefCOCO](https://arxiv.org/abs/2306.00968)


## Evaluation results

- Here's a table of models and their object detection performance results on COCO (results from [official repo](https://github.com/open-mmlab/mmdetection/blob/main/configs/mm_grounding_dino/README.md)):

    |                                                              Model                                                             | Backbone |      Pre-Train Data      |   Style   |  COCO mAP  |
    | ------------------------------------------------------------------------------------------------------------------------------ | -------- | ------------------------ | --------- | ---------- |
    |  [mm_grounding_dino_tiny_o365v1_goldg](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg)                       |  Swin-T  |        O365,GoldG        | Zero-shot | 50.4(+2.3) |
    |  [mm_grounding_dino_tiny_o365v1_goldg_grit](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg_grit)             |  Swin-T  |     O365,GoldG,GRIT      | Zero-shot | 50.5(+2.1) |
    |  [mm_grounding_dino_tiny_o365v1_goldg_v3det](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg_v3det)           |  Swin-T  |     O365,GoldG,V3Det     | Zero-shot | 50.6(+2.2) |
    |  [mm_grounding_dino_tiny_o365v1_goldg_grit_v3det](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg_grit_v3det) |  Swin-T  |  O365,GoldG,GRIT,V3Det   | Zero-shot | 50.4(+2.0) |
    |  [mm_grounding_dino_base_o365v1_goldg_v3det](https://huggingface.co/rziga/mm_grounding_dino_base_o365v1_goldg_v3det)           |  Swin-B  |     O365,GoldG,V3Det     | Zero-shot |    52.5    |
    |  [mm_grounding_dino_base_all](https://huggingface.co/rziga/mm_grounding_dino_base_all)                                         |  Swin-B  |         O365,ALL         |     -     |    59.5    |
    |  [mm_grounding_dino_large_o365v2_oiv6_goldg](https://huggingface.co/rziga/mm_grounding_dino_large_o365v2_oiv6_goldg)           |  Swin-L  | O365V2,OpenImageV6,GoldG | Zero-shot |    53.0    |
    |  [mm_grounding_dino_large_all](https://huggingface.co/rziga/mm_grounding_dino_large_all)                                       |  Swin-L  |  O365V2,OpenImageV6,ALL  |     -     |    60.3    |

- Here's a table of MM Grounding DINO tiny models and their object detection performance on LVIS (results from [official repo](https://github.com/open-mmlab/mmdetection/blob/main/configs/mm_grounding_dino/README.md)):

    |                                                              Model                                                             |    Pre-Train Data     | MiniVal APr | MiniVal APc | MiniVal APf | MiniVal AP  | Val1.0 APr | Val1.0 APc | Val1.0 APf |  Val1.0 AP  |
    | ------------------------------------------------------------------------------------------------------------------------------ | --------------------- | ----------- | ----------- | ----------- | ----------- | ---------- | ---------- | ---------- | ----------- |
    |  [mm_grounding_dino_tiny_o365v1_goldg](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg)                       |      O365,GoldG       |    28.1     |    30.2     |    42.0     | 35.7(+6.9)  |    17.1    |    22.4    |    36.5    | 27.0(+6.9)  |
    |  [mm_grounding_dino_tiny_o365v1_goldg_grit](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg_grit)             |    O365,GoldG,GRIT    |    26.6     |    32.4     |    41.8     | 36.5(+7.7)  |    17.3    |    22.6    |    36.4    | 27.1(+7.0)  |
    |  [mm_grounding_dino_tiny_o365v1_goldg_v3det](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg_v3det)           |   O365,GoldG,V3Det    |    33.0     |    36.0     |    45.9     | 40.5(+11.7) |    21.5    |    25.5    |    40.2    | 30.6(+10.5) |
    |  [mm_grounding_dino_tiny_o365v1_goldg_grit_v3det](https://huggingface.co/rziga/mm_grounding_dino_tiny_o365v1_goldg_grit_v3det) | O365,GoldG,GRIT,V3Det |    34.2     |    37.4     |    46.2     | 41.4(+12.6) |    23.6    |    27.6    |    40.5    | 31.9(+11.8) |


## BibTeX entry and citation info

```bib
@article{zhao2024open,
  title={An Open and Comprehensive Pipeline for Unified Object Grounding and Detection},
  author={Zhao, Xiangyu and Chen, Yicheng and Xu, Shilin and Li, Xiangtai and Wang, Xinjiang and Li, Yining and Huang, Haian},
  journal={arXiv preprint arXiv:2401.02361},
  year={2024}
}
```
