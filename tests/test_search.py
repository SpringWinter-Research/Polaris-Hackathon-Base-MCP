import unittest
from search import Catalog


def product(id, price, rating, count, color='Black', name='Cotton top', description='Soft jersey'):
    return dict(id=id, name=name, description=description, category='Garment Upper body',
                product_type='Vest top', audience='Ladieswear', section='Basics',
                color=color, pattern='Solid', price={'amount':price,'currency':'INR'},
                rating={'average':rating,'count':count})


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog([product('001',999,4,2),product('002',499,None,0),
                                product('003',999,5,3,'White'),
                                product('004',1499,4,2,name='Cotton skirt',description=None)])
        self.catalog.products[-1]['product_type'] = 'Skirt'
        self.catalog = Catalog(self.catalog.products)

    def ids(self, **args):
        return [p['id'] for p in self.catalog.search(args)['results']]

    def test_defaults_and_pagination(self):
        self.assertEqual(self.ids(), ['001','002','003','004'])
        self.assertEqual(self.ids(offset=1,limit=2), ['002','003'])

    def test_filters(self):
        self.assertEqual(self.ids(filters={'color':' black ','min_price':999,'max_price':999}), ['001'])
        self.assertEqual(self.ids(filters={'min_rating':4,'min_review_count':3}), ['003'])
        self.assertEqual(self.ids(filters={'color':'unknown'}), [])

    def test_sort_nulls_and_ties(self):
        self.assertEqual(self.ids(sort_by='rating',sort_order='asc'), ['001','004','003','002'])
        self.assertEqual(self.ids(sort_by='price',sort_order='desc'), ['004','001','003','002'])
        self.assertEqual(self.ids(sort_by='id'), ['004','003','002','001'])

    def test_search_and_no_matches(self):
        self.assertCountEqual(self.ids(query='COTTON top'), ['001','002','003'])
        self.assertEqual(self.ids(query='spaceship engine'), [])
        self.assertEqual(self.ids(query='   '), ['001','002','003','004'])
        recs = self.catalog.search({'query':'skirt','include_recommendations':True})['recommendations']
        self.assertTrue(all(r['for_product_id'] == '004' and r['id'] != '004' for r in recs))

    def test_invalid_arguments(self):
        for args in [{'limit':0},{'limit':True},{'offset':-1},{'sort_by':'unknown'},
                     {'unexpected':1},{'filters':{'color':' '}},
                     {'filters':{'min_price':2,'max_price':1}}, {'query':None},
                     {'filters':{'min_price':float('nan')}}, {'filters':{'min_price':float('inf')}}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.catalog.search(args)


if __name__ == '__main__': unittest.main()
