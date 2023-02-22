"""
Wrap TypegroupsClassifier as an ocrd.Processor
"""
import os
from pkg_resources import resource_filename

from ocrd import Processor
from ocrd_utils import (
    getLogger,
    make_file_id,
    assert_file_grp_cardinality,
    MIMETYPE_PAGE
)
from ocrd_utils import getLogger, make_file_id, MIMETYPE_PAGE
from ocrd_models.ocrd_page import (
    to_xml,
    TextStyleType,
    TextEquivType,
)
from ocrd_modelfactory import page_from_file
from froc import Froc
from .constants import OCRD_TOOL

class FROCProcessor(Processor):

    def __init__(self, *args, **kwargs):
        kwargs['ocrd_tool'] = OCRD_TOOL['tools']['ocrd-froc']
        kwargs['version'] = OCRD_TOOL['version']
        super().__init__(*args, **kwargs)
        if hasattr(self, 'output_file_grp'):
            # processing context
            self.setup()

    def setup(self):

        if 'network' not in self.parameter:
            self.parameter['network'] = resource_filename(__name__, 'models/default.froc')
        
        network_file = self.resolve_resource(self.parameter['network'])
        self.froc = Froc.load(network_file)

    def _process_segment(self, segment, image):
        textStyle = segment.get_TextStyle()
        if not textStyle:
            textStyle = TextStyleType()
            segment.set_TextStyle(textStyle) 
        

        method = self.parameter['method']

        classification_result = textStyle.get_fontFamily()

        if classification_result == None and method != 'COCR' :
            
            result = self.froc.classify(image)
            classification_result = ''

            for typegroup in self.froc.classMap.cl2id:
                score = result[typegroup]
                score = round(100 * score)
                if score <= 0:
                    continue
                if classification_result != '':
                    classification_result += ', '
                classification_result += '%s:%d' % (typegroup, score)

            textStyle.set_fontFamily(classification_result)
        
        
        if method == 'COCR' :
            fast_cocr = self.parameter['fast_cocr']
            transcription = self.froc.run(image, 
                                          method=method, 
                                          fast_cocr=fast_cocr)
        elif method == 'SelOCR' :
            transcription = self.froc.run(image, 
                                          method=method, 
                                          classification_result=classification_result)
        else :
            fast_cocr = self.parameter['fast_cocr']
            adaptive_treshold = self.parameter['adaptive_treshold']
            transcription = self.froc.run(image, 
                                          method=method, 
                                          classification_result=classification_result, 
                                          fast_cocr=fast_cocr, 
                                          adaptive_treshold=adaptive_treshold)
        segment.set_TextEquiv([TextEquivType(Unicode=transcription)])


    def process(self):
        """Classify historic script in pages and annotate as font style.

        Open and deserialize PAGE input files and their respective images
        down to the hierarchy ``level``.

        Then for each segment, retrieve the raw image and feed it to the font
        classifier. 

        Post-process detections by filtering classes and thresholding scores.
        Annotate the good predictions by name and score as a comma-separated
        list under ``./TextStyle/@fontFamily``, if any.

        Produce a new PAGE output file by serialising the resulting hierarchy.
        """
        LOG = getLogger('ocrd_typegroups_classifier')
        assert_file_grp_cardinality(self.input_file_grp, 1)
        assert_file_grp_cardinality(self.output_file_grp, 1)
        level = self.parameter['level']
        for n, input_file in enumerate(self.input_files):
            page_id = input_file.pageId or input_file.ID
            LOG.info('Processing: %d / %s', n, page_id)
            pcgts = page_from_file(self.workspace.download_file(input_file))
            self.add_metadata(pcgts)
            page = pcgts.get_Page()
            page_image, page_coords, image_info = self.workspace.image_from_page(
                page, page_id,
                # prefer raw image (to meet expectation of the models, which
                # have been trained on RGB images with both geometry and color
                # transform random augmentation)
                # maybe even: dewarped,deskewed ?
                feature_filter='binarized,normalized,grayscale_normalized,despeckled')

            for line in page.get_AllTextLines():
                line_image, line_coords = self.workspace.image_from_segment(
                    line, page_image, page_coords,
                    feature_filter='binarized,normalized,grayscale_normalized,despeckled')
                self._process_segment(line, line_image)

            file_id = make_file_id(input_file, self.output_file_grp)
            pcgts.set_pcGtsId(file_id)
            self.workspace.add_file(
                ID=file_id,
                file_grp=self.output_file_grp,
                pageId=input_file.pageId,
                mimetype=MIMETYPE_PAGE,
                local_filename=os.path.join(self.output_file_grp, file_id + '.xml'),
                content=to_xml(pcgts)
            )