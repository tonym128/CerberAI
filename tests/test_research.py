import unittest
import os
from pathlib import Path
from cerberai.automation import convert_markdown_to_pdf

class TestDeepResearchPDF(unittest.TestCase):
    def setUp(self):
        self.test_pdf_path = Path("./test_report.pdf")
        if self.test_pdf_path.exists():
            self.test_pdf_path.unlink()

    def tearDown(self):
        if self.test_pdf_path.exists():
            self.test_pdf_path.unlink()

    def test_pdf_conversion(self):
        markdown_content = (
            "# Superconductivity Research\n\n"
            "## Executive Summary\n"
            "This is a test summary of superconductivity.\n\n"
            "## Key Findings\n"
            "* High-Tc superconductivity is crucial.\n"
            "* Room temperature superconductors could change grids.\n\n"
            "## Detailed Analysis\n"
            "Detailed text with a **bold statement** and an *italic note* and a link: [Google](https://google.com).\n\n"
            "## References\n"
            "1. Nature Article URL: https://nature.com/articles/example"
        )
        
        self.assertFalse(self.test_pdf_path.exists())
        
        # Run conversion
        convert_markdown_to_pdf(
            markdown_content, 
            str(self.test_pdf_path.resolve()), 
            "superconductivity", 
            "2026-07-03"
        )
        
        self.assertTrue(self.test_pdf_path.exists())
        self.assertGreater(self.test_pdf_path.stat().st_size, 0)

if __name__ == "__main__":
    unittest.main()
