from dataccess import data_access
import config

def test_get_label_properties():
    config.logbook_ID = '15M5sT0r7mDlS2k5GmxdrYevoc56jChed8J85bAEI3YI'
    assert set(data_access.get_dataset_attribute_value('fe3o4lab', 'runs')) == set([608, 609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619, 602, 603, 604, 605, 606, 607])
    assert data_access.get_dataset_attribute_value('587', 'transmission') == 0.1
