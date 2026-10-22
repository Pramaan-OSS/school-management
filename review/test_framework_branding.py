from unittest import TestCase
from brand_framework import school_desktop


class TestDesktopBranding(TestCase):
    def test_support_actions_are_removed_but_local_and_added_actions_remain(self):
        entries = []
        for icon, label, order in [('pencil', 'Edit Profile', 10), ('moon', 'Toggle Theme', 20), ('info', 'About', 30), ('life-buoy', 'Support', 40)]:
            entries.append('\n\t\t\t{\n\t\t\t\ticon: "'+icon+'",\n\t\t\t\tlabel: "'+label+'",\n\t\t\t\torder: '+str(order)+',\n\t\t\t},')
        source = '\tsetup_avatar() {' + ''.join(entries) + '\nkeep_added_items(); logout();\n\t}\n\tsetup_navbar() {}'
        result = school_desktop(source)
        for expected in ['Edit Profile', 'Toggle Theme', 'keep_added_items();', 'logout();']:
            self.assertIn(expected, result)
        self.assertNotIn('label: "About"', result)
        self.assertNotIn('label: "Support"', result)
        self.assertEqual(school_desktop(result), result)

    def test_an_unexpected_framework_menu_stops_the_build(self):
        with self.assertRaises(ValueError):
            school_desktop('\tsetup_avatar() {}\n\tsetup_navbar() {}')
