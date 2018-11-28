# 
# convert_imerit_json_to_coco_json.py
#
# Takes a .json file with bounding boxes but no class labels, and a .json file containing the 
# class labels for those images, and creates a new json file with class labels and bounding 
# boxes.
#
# The bounding box .json file is in the format returned by our annotators, which is not
# actually a fully-formed .json file; rather it's a series of .json objects
#
# Leaves filenames intact.
#


#%% Imports and constants

import json
import re
import os
import uuid
from PIL import Image


#%% Configure files and paths

BASE_DIR = r'd:\temp\snapshot_serengeti_tfrecord_generation'
bboxFile = os.path.join(BASE_DIR,'microsoft_batch7_12Nov2018.json')
outputFile = os.path.join(BASE_DIR,'imerit_batch7.json')
imageBase = os.path.join(BASE_DIR,r'imerit_batch7_snapshotserengeti_2018.10.26\to_label')
databaseFile = os.path.join(BASE_DIR,'SnapshotSerengeti.json')

# For Snapshot Serengeti, we stored image IDs in our annotation files as:
#
# S1_B06_R1_PICT0008
#
# ...but the corresponding ID in the master database is actually:
#
# S1\B06\R1\S1_B06_R1_PICT0008
#
# If this is "True", we'll expand the former to the latter
SS_ID_EXPANSION = True

# Handling a one-off issue in which .'s were mysteriously replaced with -'s
# in our annotations.  This will be set dynamically, but I keep it here as 
# a constant to remind me to remove this code when we clean this issue up.
CONVERT_DOTS_TO_DASHES = False

assert(os.path.isfile(bboxFile))
assert(os.path.isfile(databaseFile))
assert(os.path.isdir(imageBase))

# Used in the (rare) case where a bounding box was added to an image that was originally
# annotated as empty
UNKNOWN_CATEGORY_ID = 1000

# Used in the (rare) case where we added bounding boxes to an image with multiple species
AMBIGUOUS_CATEGORY_ID = 1001

# Should we include ambiguous bounding boxes (with the "ambiguous" category label)
# in the output file?  Ambiguous boxes are boxes drawn on images with multiple species.
INCLUDE_AMBIGUOUS_BOXES = True


#%%  Read metadata from the master database, bounding boxes from the annotations file

with open(databaseFile, 'r') as f:
    data = json.load(f)

# The bounding box .json file is in the format returned by our annotators, which is not
# actually a fully-formed .json file; rather it's a series of .json objects
annData = []
with open(bboxFile) as annotationFileHandle:
    for line in annotationFileHandle:
        annData.append(json.loads(line))

print('Finished reading database and annotations')

# Each element of annData is a dictionary corresponding to a single sequence, with keys:
#
# annotations, categories, images
# sequence = annData[0]


#%% Build mappings for the master database

images = data['images']
annotations = data['annotations']
categories = data['categories']

# Image ID to images
im_id_to_im = {im['id']:im for im in images}

# Category ID to categiroes
cat_id_to_cat = {cat['id']:cat for cat in categories}
cat_name_to_cat_id = {cat['name']:cat['id'] for cat in categories}
empty_id = cat_name_to_cat_id['empty']

# Image ID to categories (i.e., species labels)
im_id_to_cats = {ann['image_id']:[] for ann in annotations}
for ann in annotations:
    im_id_to_cats[ann['image_id']].append(ann['category_id'])

print('Built master database mappings')


#%% Reformat annotations, grabbing category IDs from the master database (prep)

annCats = []
new_images = []
new_annotations = []
ambiguous_annotations = []
empty_sequences = []
images_not_in_db = []
cats = []
ann_images = []

image_count = 0
size_mismatch_count = 0
bbox_count = 0

new_fn_to_old_id = {}
image_id_to_bounding_box_count = {}

image_set = set()


#%% Reformat annotations, grabbing category IDs from the master database (loop)

for iSequence,sequence in enumerate(annData):
    
    sequenceImages = sequence['images']    
    sequenceAnnotations = sequence['annotations']
        
    # im = sequenceImages[0]
    
    # Are there any annotations in this sequence?
    #
    # We're still going to process all the images here, but
    # we'll continue later, before processing annotations.
    bSequenceEmpty = False
    
    if (len(sequenceAnnotations) == 0):
        empty_sequences.append(sequence)
        bSequenceEmpty = True
    
    # For each image in this sequence...
    for iImage,im in enumerate(sequenceImages):
        
        image_count += 1
        # imeritImageID = im['id']
        
        # E.g. datasetsnapshotserengeti.seqASG000001a.frame0.imgS1_B06_R1_PICT0008.JPG
        imFileName = im['file_name']
        
        # Confirm that the file exists
        imPath = os.path.join(imageBase,imFileName)
        
        # Hande a one-off issue with our annotations
        if not (os.path.isfile(imPath)):
            
            # datasetsnapshotserengeti.seqASG000001a.frame0.imgS1_B06_R1_PICT0008.JPG
            #
            # ...had become:
            #
            # datasetsnapshotserengeti.seqASG000001a-frame0.imgS1_B06_R1_PICT0008.JPG
            imFileName = imFileName.replace('-','.')
            imPath = os.path.join(imageBase,imFileName)
            
            # Does it look like we encountered this issue?
            if (os.path.isfile(imPath)):
                if (not CONVERT_DOTS_TO_DASHES):
                    print('Warning: converting .\'s to -\'s in filenames')
                CONVERT_DOTS_TO_DASHES = True
        
        assert(os.path.isfile(imPath))
        
        pat = r'\.img(.*)\.jpg$'
        m = re.findall(pat, imFileName, re.M|re.I)
        assert(len(m) == 1)
        
        if (not SS_ID_EXPANSION):
            
            old_id = m[0]
            
        else:
            # Convert:
            #
            # S1_B06_R1_PICT0008
            #
            # ...to:
            # 
            # S1/B06/B06_R1/S1_B06_R1_PICT0008            
            tokens = m[0].split('_')
            assert(len(tokens)==4)
            old_id = tokens[0] + '/' + tokens[1] + '/' + tokens[1] + '_' + tokens[2] + '/' + m[0]
            
        assert(old_id in im_id_to_im)
        
        # Make sure we only see each image once
        assert(old_id not in image_set)
        image_set.add(old_id)
        
        if old_id not in image_id_to_bounding_box_count:
            image_id_to_bounding_box_count[old_id] = 0
                
        if (bSequenceEmpty):
            assert (image_id_to_bounding_box_count[old_id] == 0)    
        
        new_fn_to_old_id[imFileName] = old_id
                
        new_im = im_id_to_im[old_id]
        new_im['file_name'] = imFileName
        assert 'height' in new_im
        assert 'width' in new_im
        if ((new_im['height'] != im['height']) or
             (new_im['width'] != im['width'])):
            imgObj = Image.open(imPath)
            size_mismatch_count = size_mismatch_count + 1
            # print('Warning: img {} was listed in DB as {}x{}, annotated as {}x{}, actual size{}x{}'.format(
            #   old_id,new_im['width'],new_im['height'],im['width'],im['height'],imgObj.width,imgObj.height))
            new_im['height'] = imgObj.height
            new_im['width'] = imgObj.width
            
        assert new_im['height'] == im['height']
        assert new_im['width'] == im['width']        
        new_images.append(new_im)
        
    # ...for each image in this sequence

    # If there are no annotations for this sequence
    if (bSequenceEmpty):
        continue
    
    # Sequences that have annotations shoud always have bboxes
    bSequenceHasBox = False
    for ann in sequenceAnnotations:
        if 'bbox' in ann:
            bSequenceHasBox = True
            break
        
    assert(bSequenceHasBox)
        
    # For each annotation in this sequence...
    # ann = sequenceAnnotations[0]
    for ann in sequenceAnnotations:
        
        # Prepare an annotation using the category ID from the database and
        # the bounding box from the annotations file
        new_ann = {}
        
        # Generate an (arbitrary) ID for this annotation; the COCO format has a concept
        # of annotation ID, but our annotation files don't
        new_ann['id'] = str(uuid.uuid1())
        imeritImageID = ann['image_id']
        
        # This was a one-off quirk with our file naming
        if (CONVERT_DOTS_TO_DASHES):
            imeritImageID = imeritImageID.replace('-','.')
        
        old_id = new_fn_to_old_id[imeritImageID]
        new_ann['image_id'] = old_id
        ann_images.append(new_ann['image_id'])
        
        ann_im = im_id_to_im[new_ann['image_id']]
        imgCats = im_id_to_cats[new_ann['image_id']]
        
        # We'll do special handling of images with multiple categories later
        new_ann['category_id'] = imgCats[0]
        
        # This annotation has no bounding box but the image wasn't originally annotated as empty
        if 'bbox' not in ann and new_ann['category_id'] != empty_id:  
            
            new_ann['category_id'] = empty_id
        
        # This annotation has a bounding box but the image was originally annotated as empty
        if 'bbox' in ann and new_ann['category_id'] == empty_id:
            
            new_ann['category_id'] = UNKNOWN_CATEGORY_ID
        
        if 'bbox' in ann:
            
            image_id_to_bounding_box_count[old_id] += 1
                
            new_ann['bbox'] = ann['bbox']
            
            # unnormalize the bbox
            new_ann['bbox'][0] = new_ann['bbox'][0]*ann_im['width']
            new_ann['bbox'][1] = new_ann['bbox'][1]*ann_im['height']
            new_ann['bbox'][2] = new_ann['bbox'][2]*ann_im['width']
            new_ann['bbox'][3] = new_ann['bbox'][3]*ann_im['height']
            bbox_count += 1            
            
        if (len(imgCats) > 1):
            
            new_ann['category_id'] = AMBIGUOUS_CATEGORY_ID
            if (INCLUDE_AMBIGUOUS_BOXES):
                new_annotations.append(new_ann)
            else:
                ambiguous_annotations.append(new_ann)    
            
        else:
            
            new_annotations.append(new_ann)
        
    # ... for each annotation in this sequence


#%% Post-processing

assert (len(image_id_to_bounding_box_count) == image_count)

# Count empty images
bboxCounts = list(image_id_to_bounding_box_count.values())
nEmptyImages = bboxCounts.count(0)

categories.append({'id':UNKNOWN_CATEGORY_ID, 'name': 'needs label'})
categories.append({'id':AMBIGUOUS_CATEGORY_ID, 'name': 'ambiguous label'})

# ...for each file
print('Processed {} boxes on {} images'.format(bbox_count,image_count))
print('{} empty sequences'.format(len(empty_sequences)))
print('{} empty images'.format(nEmptyImages))
print('Writing {} annotations on {} images'.format(len(new_images),len(new_annotations)))
if (not INCLUDE_AMBIGUOUS_BOXES):
    print('Skipped {} ambiguous annotations'.format(len(ambiguous_annotations)))
assert(len(ambiguous_annotations) + len(new_annotations) == bbox_count)

new_data = {}
new_data['images'] = new_images
new_data['categories'] = categories
new_data['annotations'] = new_annotations
new_data['info'] = data['info']
new_data['licenses'] = {}
json.dump(new_data, open(outputFile,'w'))