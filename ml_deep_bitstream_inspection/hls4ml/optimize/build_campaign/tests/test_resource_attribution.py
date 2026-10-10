from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from resource_attribution import attribute, parse_hierarchy

REPORTS=Path(__file__).resolve().parents[2]/'runs/direct_stream_20261008_002352/jobs/D_I/recovery/route_01/reports'


@unittest.skipUnless(REPORTS.exists(),'preserved routed campaign reports required')
class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.hierarchy=(REPORTS/'shell_utilization_hierarchical.rpt').read_text()
        self.summary=(REPORTS/'shell_utilization.rpt').read_text()

    def test_published_routed_counts_reconcile_without_parent_double_counting(self):
        result=attribute(self.hierarchy,self.summary,'D_I')
        self.assertEqual(result['wrapper'],dict(LUT=67382,FF=87152,BRAM_tiles=354,DSP=1328,URAM=11))
        self.assertEqual(result['components']['inference_and_publication']['resources']['BRAM_tiles'],328)
        self.assertEqual(result['components']['preprocessing']['resources']['DSP'],16)
        self.assertEqual(result['remaining_wrapper_and_interfaces']['LUT'],6607)
        self.assertEqual(result['limits_10_percent']['BRAM_tiles'],201.5)
        self.assertEqual(result['limits_10_percent']['DSP'],902)
        self.assertFalse(result['meets_resource_target']['DSP'])
        for resource,count in result['full_design'].items():
            self.assertEqual(count,result['wrapper'][resource]+result['outside_wrapper'][resource])
            self.assertEqual(result['wrapper'][resource],result['remaining_wrapper_and_interfaces'][resource]+
                             sum(component['resources'][resource] for component in result['components'].values()))

    def test_synthesis_or_mismatched_totals_cannot_be_reported_as_routed_cost(self):
        with self.assertRaisesRegex(ValueError,'Routed'):
            parse_hierarchy(self.hierarchy.replace('Physopt postRoute','Synthesized'))
        with self.assertRaisesRegex(ValueError,'totals differ'):
            attribute(self.hierarchy,self.summary.replace('188156','188157'),'D_I')

    def test_missing_preprocessing_and_duplicate_root_rejected(self):
        with self.assertRaisesRegex(ValueError,'unique hierarchy'):
            attribute(self.hierarchy.replace('checker_path.preprocess','unknown_preprocessing'),self.summary,'D_I')
        rows=self.hierarchy.splitlines()
        top=next(line for line in rows if line.startswith('| cyt_top '))
        with self.assertRaisesRegex(ValueError,'Duplicate hierarchy'):
            parse_hierarchy(self.hierarchy.replace(top,top+'\n'+top))


if __name__=='__main__':unittest.main()
