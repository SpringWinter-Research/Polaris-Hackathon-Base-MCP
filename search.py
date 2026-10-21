"""Catalog search engine for the search_products tool.

Pipeline: validate -> parse the query (budgets, colours, audience, product types,
typos, synonyms, mixed choices, complement requests) -> score candidates with an
inverted index built at startup -> sort and paginate -> complementary recommendations.
The schemas, tool contract and catalog facts are unchanged.
"""
import difflib
import json
import math
import re
from collections import OrderedDict, defaultdict
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parent
INPUT_SCHEMA = json.loads((ROOT / 'schemas/input.schema.json').read_text())
OUTPUT_SCHEMA = json.loads((ROOT / 'schemas/output.schema.json').read_text())
VALIDATOR = Draft202012Validator(INPUT_SCHEMA)
STRING_FILTERS = ('category', 'product_type', 'color', 'audience', 'section', 'pattern')


def validate_arguments(arguments):
    # Reject non-JSON floating point values even when called directly from Python.
    json.dumps(arguments, allow_nan=False)
    try:
        VALIDATOR.validate(arguments)
    except ValidationError as exc:
        raise ValueError(exc.message) from exc
    filters = arguments.get('filters', {})
    if any(not filters[k].strip() for k in STRING_FILTERS if k in filters):
        raise ValueError('String filters cannot be blank')
    if filters.get('min_price', 0) > filters.get('max_price', math.inf):
        raise ValueError('min_price cannot exceed max_price')


@lru_cache(maxsize=4096)
def tokens(text):
    return tuple(re.findall(r'\w+', text.casefold()))


# ---------------------------------------------------------------- vocabulary
STOPWORDS = set('''a an the for with and or of in on to my me i im want need looking some something any
please show find get buy that this these those is are be it its very really nice good best new item items
pair pairs set one ones each per piece also like style styled wear wearing outfit kind type look great
which what who can could would should will just only more most less cheap cheaper affordable budget
inr rs rupees rupee price priced cost costing under below upto up within max maximum over above least
than at around about from between than'''.split())

# phrase -> (product types, boost words)
SYN = {
    'tshirt': (['T-shirt'], []), 'tee': (['T-shirt'], []), 'tees': (['T-shirt'], []),
    'jeans': (['Trousers', 'Shorts'], ['denim', 'jeans']), 'jean': (['Trousers'], ['denim', 'jeans']),
    'denim': (['Trousers', 'Shorts', 'Jacket', 'Skirt', 'Dress', 'Shirt'], ['denim']),
    'pants': (['Trousers', 'Leggings/Tights'], []), 'trouser': (['Trousers'], []), 'chinos': (['Trousers'], ['chino']),
    'joggers': (['Trousers'], ['jogger', 'joggers']), 'jogger': (['Trousers'], ['jogger', 'joggers']),
    'leggings': (['Leggings/Tights'], []), 'tights': (['Underwear Tights', 'Leggings/Tights'], []),
    'shoes': (['Sneakers', 'Boots', 'Sandals', 'Other shoe', 'Ballerinas', 'Pumps', 'Flat shoe', 'Heeled sandals',
               'Wedge', 'Heels', 'Flat shoes', 'Bootie', 'Moccasins'], []),
    'footwear': (['Sneakers', 'Boots', 'Sandals', 'Other shoe', 'Ballerinas', 'Pumps', 'Flat shoe'], []),
    'trainers': (['Sneakers'], []), 'running shoes': (['Sneakers', 'Other shoe'], ['sport', 'running']),
    'sneaker': (['Sneakers'], []), 'boot': (['Boots', 'Bootie'], []), 'ankle boots': (['Boots'], ['ankle']),
    'heels': (['Heels', 'Pumps', 'Heeled sandals', 'Wedge'], []), 'sandal': (['Sandals', 'Heeled sandals'], []),
    'flip flops': (['Flip flop'], []), 'flipflops': (['Flip flop'], []), 'loafers': (['Moccasins', 'Other shoe', 'Flat shoe'], []),
    'handbag': (['Bag', 'Shoulder bag', 'Cross-body bag', 'Tote bag'], []), 'purse': (['Bag', 'Wallet'], []),
    'bags': (['Bag', 'Shoulder bag', 'Cross-body bag', 'Tote bag', 'Backpack'], []), 'tote': (['Tote bag', 'Bag'], []),
    'beach bag': (['Bag', 'Tote bag'], ['beach', 'straw']),
    'jewellery': (['Earring', 'Necklace', 'Ring', 'Bracelet'], []), 'jewelry': (['Earring', 'Necklace', 'Ring', 'Bracelet'], []),
    'earrings': (['Earring', 'Earrings'], []), 'necklaces': (['Necklace'], []), 'rings': (['Ring'], []),
    'pyjamas': (['Pyjama set', 'Pyjama bottom', 'Pyjama jumpsuit/playsuit'], []), 'pajamas': (['Pyjama set', 'Pyjama bottom'], []),
    'pyjama': (['Pyjama set', 'Pyjama bottom', 'Pyjama jumpsuit/playsuit'], []), 'pjs': (['Pyjama set'], []),
    'nightwear': (['Pyjama set', 'Night gown', 'Pyjama jumpsuit/playsuit', 'Robe'], []),
    'sleepwear': (['Pyjama set', 'Night gown', 'Pyjama jumpsuit/playsuit', 'Pyjama bottom'], []),
    'nightdress': (['Night gown'], []), 'bathrobe': (['Robe'], []),
    'swimsuit': (['Swimsuit'], []), 'swimming costume': (['Swimsuit'], []), 'bikini': (['Bikini top', 'Swimwear bottom', 'Swimwear set'], []),
    'swimwear': (['Swimsuit', 'Bikini top', 'Swimwear bottom', 'Swimwear set'], []), 'trunks': (['Swimwear bottom'], ['trunks']),
    'bikini bottoms': (['Swimwear bottom'], ['bikini']), 'swim shorts': (['Swimwear bottom'], ['shorts']),
    'romper': (['Jumpsuit/Playsuit', 'Bodysuit', 'Pyjama jumpsuit/playsuit'], []), 'playsuit': (['Jumpsuit/Playsuit'], []),
    'jumpsuit': (['Jumpsuit/Playsuit'], []), 'onesie': (['Pyjama jumpsuit/playsuit', 'Bodysuit'], []),
    'jumper': (['Sweater'], []), 'pullover': (['Sweater'], []), 'sweatshirt': (['Sweater', 'Hoodie'], ['sweatshirt']),
    'knitwear': (['Sweater', 'Cardigan'], []), 'hoodies': (['Hoodie'], []), 'hooded': (['Hoodie', 'Jacket'], []),
    'overcoat': (['Coat'], []), 'parka': (['Coat', 'Jacket'], ['parka']), 'raincoat': (['Jacket', 'Coat'], ['water']),
    'puffer': (['Jacket', 'Coat'], ['padded', 'puffer']), 'suit': (['Blazer', 'Trousers'], ['suit']),
    'cap': (['Cap/peaked', 'Cap'], []), 'caps': (['Cap/peaked', 'Cap'], []),
    'hat': (['Hat/beanie', 'Hat/brim', 'Felt hat', 'Bucket hat', 'Straw hat', 'Beanie'], []),
    'hats': (['Hat/beanie', 'Hat/brim', 'Felt hat', 'Bucket hat', 'Straw hat', 'Beanie'], []),
    'beanie': (['Hat/beanie', 'Beanie'], []), 'underwear': (['Underwear bottom', 'Underwear body', 'Underwear set', 'Bra'], []),
    'briefs': (['Underwear bottom'], []), 'boxers': (['Underwear bottom'], ['boxer']), 'panties': (['Underwear bottom'], []),
    'knickers': (['Underwear bottom'], []), 'lingerie': (['Bra', 'Underwear bottom', 'Underwear body'], []),
    'bras': (['Bra'], []), 'sock': (['Socks'], []), 'dresses': (['Dress'], []), 'gown': (['Dress'], []),
    'skirts': (['Skirt'], []), 'tops': (['Top', 'Vest top'], []), 'tank top': (['Vest top'], []), 'tank': (['Vest top'], []),
    'camisole': (['Vest top'], []), 'vest': (['Vest top', 'Outdoor Waistcoat', 'Tailored Waistcoat'], []),
    'shirts': (['Shirt'], []), 'polo': (['Polo shirt'], []), 'blouses': (['Blouse'], []), 'cardigans': (['Cardigan'], []),
    'blazers': (['Blazer'], []), 'jackets': (['Jacket'], []), 'coats': (['Coat'], []), 'sweaters': (['Sweater'], []),
    'waistcoat': (['Tailored Waistcoat', 'Outdoor Waistcoat'], []), 'gilet': (['Outdoor Waistcoat'], []),
    'shades': (['Sunglasses'], []), 'mittens': (['Gloves'], []), 'glove': (['Gloves'], []), 'belts': (['Belt'], []),
    'wallets': (['Wallet'], []), 'scarves': (['Scarf'], []), 'scarfs': (['Scarf'], []), 'ties': (['Tie'], []),
    'watches': (['Watch'], []), 'hair band': (['Hair/alice band', 'Alice band', 'Hairband'], []),
    'headband': (['Hair/alice band', 'Headband', 'Hairband'], []), 'hair clips': (['Hair clip'], []),
    'scrunchie': (['Hair string', 'Hair ties'], []), 'dungaree': (['Dungarees'], []), 'overalls': (['Dungarees', 'Outdoor overall'], []),
    'bodysuits': (['Bodysuit'], []), 'body': (['Bodysuit', 'Underwear body'], []), 'babygrow': (['Bodysuit', 'Pyjama jumpsuit/playsuit'], []),
    'backpacks': (['Backpack', 'Bag'], []), 'rucksack': (['Backpack', 'Bag'], []), 'gym bag': (['Weekend/Gym bag', 'Bag'], []),
    'sports bra': (['Bra'], ['sports', 'sport']), 'sneakers': (['Sneakers'], []), 'slipper': (['Slippers'], []),
    'kurta': (['Dress', 'Blouse', 'Top'], ['tunic']), 'tunic': (['Dress', 'Blouse', 'Top'], ['tunic']),
    'costume': (['Costumes'], []), 'toy': (['Soft Toys', 'Toy'], []), 'teddy': (['Soft Toys'], []),
}
# Context words that imply product types when no product noun is given.
INTENTS = {
    'winter': ['Sweater', 'Cardigan', 'Coat', 'Jacket', 'Hoodie', 'Scarf', 'Hat/beanie'],
    'cold': ['Sweater', 'Coat', 'Jacket', 'Cardigan', 'Hoodie'], 'cosy': ['Sweater', 'Cardigan', 'Hoodie', 'Pyjama set'],
    'cozy': ['Sweater', 'Cardigan', 'Hoodie', 'Pyjama set'], 'warm': ['Sweater', 'Coat', 'Jacket', 'Cardigan'],
    'beach': ['Swimsuit', 'Bikini top', 'Swimwear bottom', 'Shorts', 'Sandals', 'Sunglasses', 'Sarong'],
    'pool': ['Swimsuit', 'Bikini top', 'Swimwear bottom'], 'swimming': ['Swimsuit', 'Swimwear bottom', 'Bikini top'],
    'interview': ['Blazer', 'Shirt', 'Trousers', 'Blouse'], 'office': ['Blazer', 'Shirt', 'Trousers', 'Blouse'],
    'formal': ['Blazer', 'Shirt', 'Trousers', 'Tie'], 'work': ['Blazer', 'Shirt', 'Trousers', 'Blouse'],
    'newborn': ['Bodysuit', 'Garment Set', 'Pyjama jumpsuit/playsuit'], 'infant': ['Bodysuit', 'Garment Set'],
    'gym': ['Leggings/Tights', 'Top', 'Shorts', 'Bra', 'T-shirt', 'Vest top'], 'workout': ['Leggings/Tights', 'Top', 'Shorts', 'Bra', 'T-shirt'],
    'yoga': ['Leggings/Tights', 'Top', 'Bra'], 'training': ['Leggings/Tights', 'Top', 'Shorts', 'T-shirt'],
    'jogging': ['Leggings/Tights', 'Shorts', 'T-shirt', 'Sneakers'],
    'rain': ['Jacket', 'Coat', 'Umbrella'], 'rainy': ['Jacket', 'Coat', 'Umbrella'], 'monsoon': ['Jacket', 'Umbrella', 'Coat'],
    'party': ['Dress', 'Top', 'Skirt', 'Blouse'], 'wedding': ['Dress', 'Blazer'], 'dinner': ['Dress', 'Blouse', 'Shirt'],
    'date': ['Dress', 'Top', 'Blouse', 'Shirt'], 'sleep': ['Pyjama set', 'Night gown', 'Pyjama jumpsuit/playsuit'],
    'bedtime': ['Pyjama set', 'Night gown'], 'head': ['Hat/beanie', 'Cap/peaked', 'Hat/brim', 'Beanie'],
    'summer': ['Dress', 'Shorts', 'T-shirt', 'Top', 'Sandals'], 'holiday': ['Dress', 'Shorts', 'Swimsuit', 'Sandals'],
    'hiking': ['Outdoor trousers', 'Jacket', 'Outdoor Waistcoat', 'Boots'], 'snow': ['Outdoor overall', 'Jacket', 'Gloves', 'Hat/beanie'],
    'school': ['Trousers', 'Shirt', 'Skirt', 'Polo shirt'], 'lounge': ['Trousers', 'Hoodie', 'Sweater', 'Pyjama set'],
}
INTENT_WORDS = {'sequin': ['sequin', 'sequins'], 'party': ['sequin', 'glitter', 'party'], 'winter': ['wool', 'knit', 'padded', 'warm'],
                'cold': ['wool', 'padded', 'warm', 'knit'], 'cosy': ['soft', 'knit', 'fleece'], 'cozy': ['soft', 'knit', 'fleece'],
                'warm': ['wool', 'padded', 'warm', 'knit'], 'rain': ['water', 'repellent', 'rain'], 'rainy': ['water', 'repellent'],
                'monsoon': ['water', 'repellent'], 'gym': ['sport', 'sports', 'training'], 'workout': ['sport', 'training'],
                'yoga': ['sport', 'yoga'], 'beach': ['beach', 'swim'], 'summer': ['linen', 'cotton', 'light'],
                'wedding': ['lace', 'satin', 'chiffon'], 'dinner': ['satin', 'lace'], 'formal': ['tailored', 'suit'],
                'interview': ['tailored', 'suit'], 'office': ['tailored'], 'head': ['knit', 'hat'], 'sleep': ['pyjama'],
                'hiking': ['outdoor', 'water'], 'snow': ['padded', 'water']}
INTENT_AUDIENCE = {'newborn': 'baby', 'infant': 'baby', 'gym': 'sport', 'workout': 'sport', 'yoga': 'sport', 'training': 'sport'}

COLOURS = {'black': ['black'], 'white': ['white'], 'blue': ['blue'], 'navy': ['dark blue'], 'red': ['red'], 'green': ['green'],
           'grey': ['grey'], 'gray': ['grey'], 'pink': ['pink'], 'beige': ['beige'], 'cream': ['off white', 'light beige'],
           'yellow': ['yellow'], 'orange': ['orange'], 'purple': ['purple'], 'lilac': ['light purple'], 'violet': ['purple'],
           'turquoise': ['turquoise'], 'khaki': ['khaki'], 'olive': ['khaki', 'dark green'], 'brown': ['brown', 'dark beige'],
           'tan': ['beige', 'brown'], 'gold': ['gold'], 'golden': ['gold'], 'silver': ['silver'], 'maroon': ['dark red'],
           'burgundy': ['dark red'], 'mint': ['light green'], 'teal': ['turquoise'], 'copper': ['bronze/copper']}
MODS = {'light', 'dark', 'off'}
AUDIENCE_WORDS = {'men': 'men', 'mens': 'men', 'man': 'men', 'male': 'men', 'guys': 'men', 'boyfriend': 'men', 'husband': 'men',
                  'gents': 'men', 'women': 'women', 'womens': 'women', 'woman': 'women', 'ladies': 'women', 'lady': 'women',
                  'female': 'women', 'girlfriend': 'women', 'wife': 'women', 'kids': 'kids', 'kid': 'kids', 'children': 'kids',
                  'child': 'kids', 'boys': 'kids', 'boy': 'kids', 'girls': 'kids', 'girl': 'kids', 'toddler': 'kids',
                  'teen': 'kids', 'baby': 'baby', 'babies': 'baby', 'newborn': 'baby', 'infant': 'baby', 'menswear': 'men', 'ladieswear': 'women', 'womenswear': 'women', 'kidswear': 'kids'}


def audience_group(aud):
    a = aud.casefold()
    if a.startswith('baby'): return 'baby'
    if a.startswith('children'): return 'kids'
    if a == 'menswear': return 'men'
    if a == 'sport': return 'sport'
    return 'women'


PRICE_MAX = re.compile(r'(?:under|below|less than|lower than|cheaper than|upto|up to|within|max(?:imum)?|not more than|no more than|at most|<)\s*(?:inr|rs\.?|₹|rupees)?\s*(\d[\d,]*)\s*(?:inr|rs|rupees|₹|/-)?(?:\s*each)?')
PRICE_MIN = re.compile(r'(?:over|above|more than|at least|min(?:imum)?|starting at|from|>)\s*(?:inr|rs\.?|₹|rupees)?\s*(\d[\d,]*)\s*(?:inr|rs|rupees|₹|/-)?(?:\s*each)?')
PRICE_BETWEEN = re.compile(r'between\s*(?:inr|rs\.?|₹)?\s*(\d[\d,]*)\s*(?:and|-|to)\s*(?:inr|rs\.?|₹)?\s*(\d[\d,]*)\s*(?:inr|rs|rupees)?')
COMPLEMENT = [
    re.compile(r'\b(?:with|and|plus)\s+(?:a|an|some|the)?\s*(?:matching|coordinating|complementary|complimentary)\s+(.+)$'),
    re.compile(r'\bwith\s+(?:a|an|some|the)?\s*(.+?)\s+to\s+(?:match|go with it|go with)\b.*$'),
    re.compile(r'\b(?:and|with|plus)\s+(.+?)\s+to\s+go\s+with\s+(?:it|them)\b.*$'),
    re.compile(r'\b(?:and|with)\s+(something|anything|accessories)\s+(?:to\s+(?:go\s+with|match|pair\s+with)|that\s+goes\s+with)\b.*$'),
    re.compile(r'\b(?:paired|to pair|that pairs|teamed)\s+with\s+(?:a|an|some)?\s*(.+)$'),
    re.compile(r'\bwith\s+(?:a|an|some)?\s*(.+)$'),
]
SPLIT = re.compile(r'\s*(?:,|&|/|\+|\band\b|\bor\b|\bplus\b|\bversus\b|\bvs\b)\s*')

COMPLEMENTS = {
    'dress': ['Bag', 'Sandals', 'Heeled sandals', 'Earring', 'Necklace', 'Pumps'],
    'skirt': ['Blouse', 'Top', 'Bag', 'Sandals'], 'trousers': ['T-shirt', 'Shirt', 'Belt', 'Sneakers'],
    'shorts': ['T-shirt', 'Vest top', 'Sandals', 'Sneakers'], 't-shirt': ['Shorts', 'Trousers', 'Sneakers', 'Cap/peaked'],
    'shirt': ['Trousers', 'Tie', 'Belt', 'Blazer'], 'polo shirt': ['Shorts', 'Trousers', 'Belt'],
    'blouse': ['Skirt', 'Trousers', 'Necklace', 'Earring'], 'top': ['Skirt', 'Shorts', 'Trousers'], 'vest top': ['Skirt', 'Shorts', 'Trousers'],
    'sweater': ['Trousers', 'Scarf', 'Hat/beanie'], 'cardigan': ['Top', 'Dress', 'Trousers'], 'hoodie': ['Trousers', 'Sneakers', 'Cap/peaked'],
    'jacket': ['Scarf', 'Gloves', 'Hat/beanie', 'Boots'], 'coat': ['Scarf', 'Gloves', 'Hat/beanie', 'Boots'],
    'blazer': ['Trousers', 'Shirt', 'Tie'], 'bikini top': ['Swimwear bottom', 'Sunglasses', 'Sarong'],
    'swimwear bottom': ['Bikini top', 'Sunglasses'], 'swimsuit': ['Sunglasses', 'Sarong', 'Bag', 'Flip flop'],
    'bra': ['Underwear bottom'], 'underwear bottom': ['Bra'], 'pyjama set': ['Slippers', 'Robe'], 'night gown': ['Slippers', 'Robe'],
    'bodysuit': ['Trousers', 'Hat/beanie', 'Socks'], 'sneakers': ['Socks', 'T-shirt'], 'boots': ['Socks', 'Trousers'],
    'sandals': ['Dress', 'Bag'], 'bag': ['Wallet', 'Sunglasses'], 'jumpsuit/playsuit': ['Sandals', 'Bag'],
    'leggings/tights': ['Top', 'Bra', 'Sneakers'], 'garment set': ['Socks', 'Hat/beanie'], 'dungarees': ['T-shirt', 'Top'],
    'tie': ['Shirt'], 'belt': ['Trousers'], 'scarf': ['Gloves', 'Hat/beanie'], 'gloves': ['Scarf', 'Hat/beanie'],
    'hat/beanie': ['Scarf', 'Gloves'], 'socks': ['Sneakers'], 'earring': ['Necklace', 'Bracelet'], 'necklace': ['Earring', 'Bracelet'],
}
NEUTRAL = {'black', 'white', 'off white', 'grey', 'light beige', 'beige'}


def parse_price(text):
    lo, hi = None, None
    m = PRICE_BETWEEN.search(text)
    if m:
        lo, hi = float(m[1].replace(',', '')), float(m[2].replace(',', ''))
        text = text[:m.start()] + ' ' + text[m.end():]
    m = PRICE_MAX.search(text)
    if m:
        hi = float(m[1].replace(',', '')); text = text[:m.start()] + ' ' + text[m.end():]
    m = PRICE_MIN.search(text)
    if m:
        lo = float(m[1].replace(',', '')); text = text[:m.start()] + ' ' + text[m.end():]
    text = re.sub(r'(?:₹|\brs\.?|\binr)\s*\d[\d,]*|\d[\d,]*\s*(?:rupees|inr|rs)\b', ' ', text)
    return text, lo, hi


class Catalog:
    def __init__(self, products):
        self.products = sorted(products, key=lambda p: p['id'])
        P = self.products
        self.n = len(P)
        self.words = {p['id']: set(tokens(' '.join(str(p.get(k) or '') for k in ('name', 'description', *STRING_FILTERS)))) for p in P}
        self.ptype = [str(p.get('product_type') or '').casefold() for p in P]
        self.color = [str(p.get('color') or '').casefold() for p in P]
        self.group = [audience_group(str(p.get('audience') or '')) for p in P]
        self.name_tok = [set(tokens(p['name'] or '')) for p in P]
        self.desc_tok = [set(tokens(' '.join(str(p.get(k) or '') for k in ('description', 'pattern', 'section')))) for p in P]
        self.price = [p['price']['amount'] for p in P]
        self.quality = [((p['rating']['average'] or 3.0) * math.log1p(p['rating']['count'])) for p in P]
        # inverted indexes
        self.by_value = {k: defaultdict(list) for k in STRING_FILTERS}
        self.by_type = defaultdict(list)
        self.by_word = defaultdict(set)
        for i, p in enumerate(P):
            for k in STRING_FILTERS:
                self.by_value[k][str(p.get(k) or '').strip().casefold()].append(i)
            self.by_type[self.ptype[i]].append(i)
            for w in self.name_tok[i] | self.desc_tok[i]:
                self.by_word[w].add(i)
        self.by_type_quality = {t: sorted(ix, key=lambda i: (-self.quality[i], P[i]['id'])) for t, ix in self.by_type.items()}
        # product-type phrase lexicon
        self.lex = {}
        for t in self.by_type:
            if t in ('unknown', ''): continue
            for form in {t, *t.split('/')}:
                form = form.strip()
                if not form: continue
                self.lex.setdefault(form, (set(), set()))[0].add(t)
                if not form.endswith('s'):
                    self.lex.setdefault(form + 's', (set(), set()))[0].add(t)
        self.lex['shirt'] = ({'shirt'}, set()); self.lex['shirts'] = ({'shirt'}, set())
        for k, (ts, ws) in SYN.items():
            e = self.lex.setdefault(k, (set(), set()))
            e[0].update(t.casefold() for t in ts if t.casefold() in self.by_type); e[1].update(ws)
        for k in list(self.lex):
            self.lex[k.replace('-', '')] = self.lex[k]
        self.max_phrase = max(len(k.split()) for k in self.lex)
        freq = defaultdict(int)
        for i in range(self.n):
            for w in self.name_tok[i]: freq[w] += 1
        self.vocab = set(self.by_word) | set(STOPWORDS) | set(AUDIENCE_WORDS) | set(COLOURS) | set(INTENTS) | {w for k in self.lex for w in k.split()}
        self.correct_to = sorted({w for k in self.lex for w in k.split()} | set(COLOURS) | set(AUDIENCE_WORDS) | set(INTENTS)
                                 | {w for w, c in freq.items() if c >= 30 and len(w) >= 4 and not w.isdigit()})
        self.freq = dict(freq)
        self.keyterms = {w for k in self.lex for w in k.split()} | set(COLOURS) | set(AUDIENCE_WORDS) | set(INTENTS)
        self.keyterm_list = sorted(self.keyterms)
        self.cache = OrderedDict()

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    # ------------------------------------------------------------ query parsing
    @lru_cache(maxsize=4096)
    def fix(self, w):
        if w in self.keyterms or w in STOPWORDS or len(w) < 4 or any(c.isdigit() for c in w):
            return w
        # Prefer shopping terms (types, colours, audiences) over rare catalog spellings.
        if len(self.by_word.get(w, ())) < 40:
            m = difflib.get_close_matches(w, self.keyterm_list, 1, 0.8)
            if m: return m[0]
        if w in self.vocab:
            return w
        m = difflib.get_close_matches(w, self.correct_to, 1, 0.8)
        return m[0] if m else w

    def parse_part(self, text):
        toks = [self.fix(t) for t in tokens(text)]
        types, boost, colours, groups, words, intents = set(), set(), [], set(), [], set()
        i = 0
        while i < len(toks):
            for n in range(min(self.max_phrase, len(toks) - i), 0, -1):
                ph = ' '.join(toks[i:i + n])
                if n == 1 and toks[i] in MODS and i + 1 < len(toks) and toks[i + 1] in COLOURS:
                    colours.append([f'{toks[i]} {c}' if toks[i] != 'off' else 'off white' for c in COLOURS[toks[i + 1]]]); i += 2; break
                if ph in self.lex and self.lex[ph][0]:
                    types |= self.lex[ph][0]; boost |= self.lex[ph][1]; i += n; break
                if n == 1:
                    w = toks[i]
                    if w in COLOURS: colours.append(COLOURS[w])
                    elif w in AUDIENCE_WORDS: groups.add(AUDIENCE_WORDS[w])
                    elif w in INTENTS: intents.add(w)
                    elif w in self.lex: boost |= self.lex[w][1]
                    elif w not in STOPWORDS: words.append(w)
                    i += 1
        return dict(types=types, boost=boost, colours=colours, groups=groups, words=words, intents=intents)

    def parse(self, query, with_recs):
        q = query.casefold().replace('t-shirt', 'tshirt').replace('t shirt', 'tshirt').replace("'s", 's')
        comp = None
        for rx in COMPLEMENT:
            m = rx.search(q)
            if m:
                tail = m[1]
                ttxt, _, _ = parse_price(tail)
                tp = self.parse_part(ttxt)
                head_parsed = self.parse_part(parse_price(q[:m.start()])[0])
                generic = tail.split()[0] in ('something', 'anything', 'accessories')
                if (tp['types'] or generic) and (head_parsed['types'] or head_parsed['intents']):
                    comp = (tail, generic); q = q[:m.start()]
                    break
        q, lo, hi = parse_price(q)
        raw_parts = [x for x in SPLIT.split(q) if x.strip()]
        parsed = [self.parse_part(x) for x in raw_parts]
        typed = [p for p in parsed if p['types']]
        if len(typed) >= 2:
            # attach untyped fragments (modifiers like "for men" or "in grey") to all choices
            extra = [p for p in parsed if not p['types']]
            parts = typed
            for e in extra:
                for p in parts:
                    if not p['colours']: p['colours'] = list(e['colours'])
                    p['groups'] |= e['groups']; p['words'] += e['words']; p['intents'] |= e['intents']
            gs = set().union(*[p['groups'] for p in parts])
            for p in parts:
                if not p['groups']: p['groups'] = set(gs)
            if 'in' in q.split():  # "cardigan or sweater in grey" shares the colour
                cs = next((p['colours'] for p in reversed(parts) if p['colours']), [])
                for p in parts:
                    if not p['colours']: p['colours'] = list(cs)
        else:
            parts = [self.parse_part(q)]
        for p in parts:
            p['lo'], p['hi'] = lo, hi
        cpart = None
        if comp and with_recs:
            ctext, generic = comp
            ctext, clo, chi = parse_price(ctext)
            cpart = self.parse_part(ctext) if not generic else dict(types=set(), boost=set(), colours=[], groups=set(), words=[], intents=set())
            cpart['lo'], cpart['hi'] = clo, chi
            cpart['groups'] = cpart['groups'] or set().union(*[p['groups'] for p in parts])
        return parts, cpart

    # ------------------------------------------------------------ scoring
    def colour_ok(self, i, colours):
        c = self.color[i]
        return all(any(x in c for x in alt) for alt in colours)

    def group_ok(self, i, groups):
        if not groups: return True
        g = self.group[i]
        return g in groups or (g == 'sport' and groups & {'men', 'women'})

    def score_part(self, part, cand):
        """Return {index: score} for one choice; empty when nothing recognisable."""
        types = set(part['types'])
        intent_types = set()
        for w in part['intents']:
            intent_types |= {t.casefold() for t in INTENTS[w] if t.casefold() in self.by_type}
        groups = set(part['groups']) | {INTENT_AUDIENCE[w] for w in part['intents'] if w in INTENT_AUDIENCE and not types}
        hard_groups = {g for g in groups if g != 'sport'}
        boost = set(part['boost'])
        soft = {w for k in part['intents'] for w in INTENT_WORDS.get(k, [])} - boost
        words = part['words']
        if types:
            pool = set()
            for t in types: pool.update(self.by_type[t])
        elif intent_types:
            pool = set()
            for t in intent_types: pool.update(self.by_type[t])
        else:
            # no product noun: strict lexical match on remaining words (keeps unrelated requests empty)
            content = words + sorted(boost)
            soft = set()
            if not content and not part['colours'] and not groups:
                return {}
            pool = None
            for w in content:
                s = self.by_word.get(w, set())
                pool = set(s) if pool is None else pool & s
            if pool is None:
                pool = set(range(self.n))
            words = []
        lo, hi = part['lo'], part['hi']
        out = {}
        for i in pool:
            if cand is not None and i not in cand: continue
            if hi is not None and self.price[i] > hi: continue
            if lo is not None and self.price[i] < lo: continue
            if part['colours'] and not self.colour_ok(i, part['colours']): continue
            if hard_groups and not self.group_ok(i, hard_groups): continue
            nt, dt = self.name_tok[i], self.desc_tok[i]
            s = 10.0 if (types and self.ptype[i] in types) else 6.0
            if intent_types and self.ptype[i] in intent_types: s += 2
            s += sum(3 if w in nt else 1.5 if w in dt else 0 for w in boost)
            s += sum(1 if w in nt or w in dt else 0 for w in soft)
            s += sum(4 if w in nt else 3 if w in dt else 0 for w in words)
            if 'sport' in groups and self.group[i] == 'sport': s += 2
            s += min(1.0, self.quality[i] / 15)
            out[i] = s
        if words and out:
            # require at least half of the extra descriptive words when anything matches them
            best = max(out.values())
            out = {i: v for i, v in out.items() if v >= best - 4 * len(words) + 1} if best > 12 else out
        return out

    def rank(self, query, filters, with_recs):
        parts, cpart = self.parse(query, with_recs)
        cand = None
        if filters:
            cand = set(self.filter_indices(filters))
        lists = []
        for p in parts:
            sc = self.score_part(p, cand)
            lists.append(sorted(sc, key=lambda i: (-sc[i], self.products[i]['id'])))
        if len(lists) == 1:
            order = lists[0]
        else:
            seen, order = set(), []
            for row in zip_longest_lists(lists):
                for i in row:
                    if i not in seen: seen.add(i); order.append(i)
        return order, parts, cpart

    def filter_indices(self, filters):
        idx = None
        for k in STRING_FILTERS:
            if k in filters:
                lst = self.by_value[k].get(filters[k].strip().casefold(), [])
                if idx is None or len(lst) < len(idx): idx = lst
        if idx is None: idx = range(self.n)
        P = self.products
        return [i for i in idx if self.matches(P[i], filters)]

    # ------------------------------------------------------------ recommendations
    def recommend(self, results, arguments, parts=None, cpart=None):
        if not results:
            return []
        P = self.products
        pos = {p['id']: i for i, p in enumerate(P)} if not hasattr(self, '_pos') else self._pos
        self._pos = pos
        prim = [pos[r['id']] for r in results]
        used = set(prim)
        groups_q = set().union(*[p['groups'] for p in parts]) if parts else set()
        recs = []
        targets = prim[:5] if cpart is None or not cpart['types'] else prim[:5]
        for rnd in range(3):
            for pi in targets:
                if len(recs) >= 5: break
                if cpart is not None and cpart['types']:
                    ctypes = list(cpart['types'])
                else:
                    ctypes = [t.casefold() for t in COMPLEMENTS.get(self.ptype[pi], [])]
                ctypes = [t for t in ctypes if t in self.by_type_quality and t != self.ptype[pi]]
                if not ctypes: continue
                best, bs = None, None
                for rank_t, t in enumerate(ctypes):
                    for i in self.by_type_quality[t][:400]:
                        if i in used: continue
                        if cpart is not None:
                            if cpart['hi'] is not None and self.price[i] > cpart['hi']: continue
                            if cpart['lo'] is not None and self.price[i] < cpart['lo']: continue
                            if cpart['colours'] and not self.colour_ok(i, cpart['colours']): continue
                        g = self.group[pi]
                        hard = {x for x in groups_q if x != 'sport'}
                        if hard and not self.group_ok(i, hard): continue
                        if not hard and g in ('men', 'kids', 'baby') and self.group[i] != g: continue
                        if not hard and g == 'women' and self.group[i] in ('men', 'kids', 'baby'): continue
                        s = 6 - rank_t * 1.0 + min(2, self.quality[i] / 8)
                        if self.color[i] == self.color[pi]: s += 2
                        elif self.color[i] in NEUTRAL: s += 1
                        if cpart is not None:
                            s += sum(2 for w in cpart['words'] + sorted(cpart['boost']) if w in self.name_tok[i] or w in self.desc_tok[i])
                        if bs is None or s > bs or (s == bs and P[i]['id'] < P[best]['id']):
                            best, bs = i, s
                if best is not None:
                    used.add(best)
                    c, p = P[best], P[pi]
                    recs.append({'id': c['id'], 'for_product_id': p['id'],
                                 'reason': f"{c['color']} {c['product_type'].lower()} that complements the {p['color'].lower()} {p['product_type'].lower()}"})
            if len(recs) >= 5 or (cpart is None or not cpart['types']) and rnd >= 0 and len(recs) >= min(5, len(targets)):
                break
        return recs[:5]

    @staticmethod
    def matches(product, filters):
        for key in STRING_FILTERS:
            if key in filters and str(product.get(key) or '').strip().casefold() != filters[key].strip().casefold():
                return False
        price = product['price']['amount']
        average = product['rating']['average']
        return (price >= filters.get('min_price', 0)
                and price <= filters.get('max_price', math.inf)
                and ('min_rating' not in filters or
                     (average is not None and average >= filters['min_rating']))
                and product['rating']['count'] >= filters.get('min_review_count', 0))

    def search(self, arguments):
        validate_arguments(arguments)
        key = json.dumps(arguments, sort_keys=True)
        hit = self.cache.get(key)
        if hit is not None:
            self.cache.move_to_end(key)
            return json.loads(hit)
        out = self._search(arguments)
        self.cache[key] = json.dumps(out)
        if len(self.cache) > 4096: self.cache.popitem(last=False)
        return out

    def _search(self, arguments):
        query = arguments.get('query', '').strip()
        filters = arguments.get('filters', {})
        with_recs = arguments.get('include_recommendations', False)
        P = self.products
        parts = cpart = None
        if query:
            order, parts, cpart = self.rank(query, filters, with_recs)
            candidates = [P[i] for i in order]
        else:
            candidates = [P[i] for i in self.filter_indices(filters)]
        sort_by = arguments.get('sort_by', 'relevance')
        reverse = arguments.get('sort_order', 'desc') == 'desc'
        if sort_by == 'relevance':
            if query and not reverse:
                candidates = candidates[::-1]
        elif sort_by == 'rating':
            candidates.sort(key=lambda p: p['id'])
            rated = [p for p in candidates if p['rating']['average'] is not None]
            unrated = [p for p in candidates if p['rating']['average'] is None]
            rated.sort(key=lambda p: p['rating']['average'], reverse=reverse)
            candidates = rated + unrated
        else:
            candidates.sort(key=lambda p: p['id'])
            key = {'id': lambda p: p['id'], 'price': lambda p: p['price']['amount'],
                   'review_count': lambda p: p['rating']['count']}[sort_by]
            candidates.sort(key=key, reverse=reverse)
            if sort_by == 'id' and reverse:
                pass
        offset, limit = arguments.get('offset', 0), arguments.get('limit', 10)
        results = [{'id': p['id']} for p in candidates[offset:offset + limit]]
        recs = self.recommend(results, arguments, parts, cpart) if results and with_recs and query else []
        return {'results': results, 'recommendations': recs}


def zip_longest_lists(lists):
    n = max((len(l) for l in lists), default=0)
    for k in range(n):
        yield [l[k] for l in lists if k < len(l)]
