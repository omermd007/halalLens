import type { IngredientRuleDef, ResolutionKey, StatusKey, Tone } from './types';

export function canon(s: string | null | undefined): string {
  return (
    ' ' +
    String(s || '')
      .toLowerCase()
      .replace(/&/g, ' and ')
      .replace(/['\u2019]/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim() +
    ' '
  );
}

interface RawRule extends Omit<IngredientRuleDef, 'aliasCanon'> {}

const RAW_RULES: RawRule[] = [
  {
    id: 'pork_gelatin',
    name: 'pork gelatin',
    risk: 'haram',
    aliases: ['pork gelatin', 'porcine gelatin', 'gelatin pork', 'gelatin porcine', 'pork gelatine'],
    plain: 'Gelatin made from pigs. Not halal.',
    context: 'Common in U.S. gummies, marshmallows, and some yogurts and frostings.',
    kosher: 'Never kosher or vegan.',
    question: 'Is pork/porcine gelatin used in this product?',
  },
  {
    id: 'pork',
    name: 'pork & pork fat',
    risk: 'haram',
    aliases: [
      'pork', 'porcine', 'bacon', 'ham', 'lard', 'pork fat', 'pepperoni',
      'prosciutto', 'pancetta', 'chorizo', 'salami', 'pork rind', 'pork rinds',
    ],
    plain: 'Pork or pork fat. Not halal.',
    context: 'Found in refried beans (lard), pizzas (pepperoni), soups and snack seasonings.',
    kosher: 'Never kosher.',
    question: 'Does this product contain any pork or pork-derived ingredients?',
  },
  {
    id: 'carmine',
    name: 'carmine',
    risk: 'haram',
    aliases: ['carmine', 'cochineal', 'cochineal extract', 'carminic acid', 'crimson lake', 'natural red 4'],
    plain: 'Red color made from crushed insects. Most scholars treat it as not permissible.',
    context: 'Used in U.S. yogurts, candies, juices and red frostings.',
    kosher: 'Not kosher, not vegan.',
    question: 'Is carmine/cochineal used as a colorant?',
  },
  {
    id: 'alcohol_bev',
    name: 'wine, beer & liquor',
    risk: 'haram',
    aliases: [
      'wine', 'red wine', 'white wine', 'cooking wine', 'rum', 'beer', 'brandy',
      'bourbon', 'whiskey', 'whisky', 'liqueur', 'sherry', 'mirin', 'sake', 'vodka',
    ],
    exclude: / vinegar /,
    plain: 'An alcoholic drink used as an ingredient. Not halal.',
    context: 'Found in sauces, marinades, desserts and some flavorings.',
    kosher: 'Kosher wine is still alcohol.',
    question: 'Is wine, beer or liquor used in this product?',
  },
  {
    id: 'meat',
    name: 'meat & poultry',
    risk: 'meat',
    aliases: [
      'chicken', 'beef', 'turkey', 'lamb', 'veal', 'mutton', 'goat', 'meat', 'poultry',
      'chicken fat', 'beef fat', 'tallow', 'beef tallow', 'chicken broth', 'beef broth',
      'chicken stock', 'beef stock', 'beef extract', 'chicken powder', 'beef gelatin', 'bovine gelatin',
    ],
    exclude: / (halal|zabiha|coconut|meatless|plant based|vegan|vegetarian) /,
    plain: "Meat must come from halal (zabiha) slaughter. Without halal certification, it isn't considered halal.",
    context: 'Most U.S. meat, broth and animal fat is not zabiha unless certified (IFANCA, HFSAA, ISWA, etc.).',
    kosher: 'Kosher meat follows different slaughter rules; views differ on accepting it.',
    question: 'Is the meat/poultry from halal (zabiha) slaughter, and is it halal-certified?',
  },
  {
    id: 'enzymes',
    name: 'enzymes',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: [
      'enzymes', 'enzyme', 'rennet', 'animal rennet', 'microbial enzymes', 'cheese enzymes',
      'lipase', 'pepsin', 'non animal enzymes', 'microbial rennet', 'vegetable rennet',
    ],
    plain: 'Used to make cheese. Can come from microbes (fine) or from animal stomachs (pig or non-zabiha calf).',
    context: "U.S. labels rarely say which. Generic 'enzymes' can be microbial, fermentation-made chymosin (FPC), or animal rennet.",
    kosher: 'OU-D cheese avoids pork rennet, but some kosher lines allow calf rennet. Certified vegan rules out animal enzymes.',
    question: 'Are the enzymes used in this product 100% microbial/non-animal, or are any animal-derived enzymes (porcine/bovine rennet, pepsin, lipase) used?',
  },
  {
    id: 'cheese_culture',
    name: 'cheese culture',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: ['cheese culture', 'cheese cultures'],
    plain: "Bacteria used to make cheese. Usually fine, but it's paired with enzymes whose source is unknown.",
    context: 'Cultures are microbial, but some growth media and the matching rennet can be animal-derived.',
    kosher: 'Kosher dairy excludes pork media.',
    question: 'Are the cheese cultures and the enzymes used with them free of animal-derived rennet or media?',
  },
  {
    id: 'whey',
    name: 'whey',
    risk: 'mushbooh',
    strict: 'whey',
    aliases: [
      'whey', 'sweet whey', 'whey powder', 'dried whey', 'whey protein',
      'whey protein concentrate', 'whey protein isolate', 'modified whey',
    ],
    plain: 'Leftover liquid from cheesemaking. Inherits the source of the cheese enzymes.',
    context: 'Whey from cheese made with animal rennet is a concern for strict observers.',
    kosher: 'Lenient views accept whey (istihalah / OU-D supervision); strict views ask for the rennet source.',
    question: 'Is the whey sourced only from cheese made with microbial/non-animal enzymes?',
  },
  {
    id: 'mono_di',
    name: 'mono- and diglycerides',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: [
      'mono and diglycerides', 'monoglycerides', 'diglycerides', 'mono and di glycerides',
      'mono diglycerides', 'monoglyceride', 'distilled monoglycerides',
    ],
    plain: 'Emulsifiers made from fat. Can be from soy/palm oil or from beef/pork fat.',
    context: 'Very common in U.S. bread, ice cream, peanut butter and boxed mixes.',
    kosher: "OU-Pareve or certified vegan means plant-based. Generic 'K' has no agency oversight.",
    question: 'Are the mono- and diglycerides 100% plant/vegetable-derived, and does the source ever vary by supplier?',
  },
  {
    id: 'stearates',
    name: 'fat-based emulsifiers',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: [
      'sodium stearoyl lactylate', 'calcium stearoyl lactylate', 'stearic acid',
      'magnesium stearate', 'calcium stearate', 'polysorbate 60', 'polysorbate 80',
      'sorbitan monostearate', 'glyceryl monostearate',
    ],
    plain: 'Made from fatty acids that can be plant- or animal-derived.',
    context: 'Used in U.S. breads, frostings, candy and supplements.',
    kosher: 'OU-Pareve or vegan certification indicates plant source.',
    question: 'Are these emulsifiers derived 100% from vegetable sources?',
  },
  {
    id: 'gelatin',
    name: 'gelatin',
    risk: 'mushbooh',
    aliases: ['gelatin', 'gelatine', 'kosher gelatin', 'fish gelatin', 'kosher fish gelatin', 'halal gelatin'],
    plain: 'Usually made from pig or non-zabiha cow skin and bones unless it says fish or halal.',
    context: 'Unspecified gelatin in U.S. candy and marshmallows is most often pork.',
    kosher: "'Kosher gelatin' can be fish or bovine; ask which.",
    question: 'What is the exact source of the gelatin (pork, beef, fish, or plant)?',
  },
  {
    id: 'natural_flavors',
    name: 'natural flavors',
    risk: 'mushbooh',
    strict: 'nf',
    aliases: [
      'natural flavor', 'natural flavors', 'natural flavoring', 'natural flavorings',
      'natural flavour', 'natural flavours', 'natural and artificial flavors',
      'natural and artificial flavor', 'artificial and natural flavors',
      'artificial and natural flavor', 'other natural flavors',
    ],
    plain: 'An umbrella FDA term. May include animal-derived ingredients or alcohol as a carrier.',
    context: "Brands don't have to disclose what's inside; usually plant-based, sometimes not.",
    kosher: 'Vegan rules out animals but not alcohol carriers.',
    question: 'Do the natural flavors contain any animal-derived ingredients or ethyl alcohol carriers?',
  },
  {
    id: 'glycerin',
    name: 'glycerin',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: ['glycerin', 'glycerine', 'glycerol', 'vegetable glycerin'],
    plain: 'A sweet moisturizer. Can be plant, synthetic, or animal-fat based.',
    context: 'Common in U.S. nutrition bars, frostings and soft-baked snacks.',
    kosher: 'OU-Pareve and vegan glycerin is plant-based.',
    question: 'Is the glycerin 100% vegetable-derived or synthetic?',
  },
  {
    id: 'lcysteine',
    name: 'L-cysteine',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: ['l cysteine', 'l cysteine hydrochloride', 'cysteine'],
    plain: 'Dough softener. Can come from feathers, hair, or microbial fermentation.',
    context: 'Found in some U.S. bagels, pizza crusts and fast-food buns.',
    kosher: 'Vegan certification means fermentation/synthetic.',
    question: 'Is the L-cysteine produced via fermentation/synthetic means (not feathers or hair)?',
  },
  {
    id: 'vanilla',
    name: 'vanilla extract',
    risk: 'mushbooh',
    strict: 'ethanol',
    aliases: ['vanilla extract', 'pure vanilla extract', 'bourbon vanilla extract'],
    plain: 'U.S. pure vanilla extract is legally at least 35% alcohol. Many scholars allow it in tiny amounts; strict views avoid it.',
    context: 'FDA standard of identity requires ethyl alcohol as the solvent.',
    kosher: 'Kosher and vegan both allow it.',
    question: 'Is the vanilla flavoring extracted with ethyl alcohol or alcohol-free?',
  },
  {
    id: 'ethanol',
    name: 'alcohol (solvent)',
    risk: 'mushbooh',
    strict: 'ethanol',
    aliases: ['alcohol', 'ethyl alcohol', 'ethanol', 'grain alcohol'],
    exclude: / (sugar|cetyl|stearyl|cetearyl|benzyl|polyvinyl|fatty) alcohol |alcohol free|non alcoholic/,
    plain: 'Alcohol used as a flavor carrier or preservative.',
    context: 'Usually trace amounts in flavorings and frostings.',
    kosher: 'Kosher and vegan both allow it.',
    question: 'How much ethyl alcohol remains in the final product, and what is it used for?',
  },
  {
    id: 'shellac',
    name: "confectioner's glaze",
    risk: 'mushbooh',
    aliases: ['confectioners glaze', 'confectioner s glaze', 'resinous glaze', 'shellac', 'pharmaceutical glaze'],
    plain: 'Shiny coating made by lac insects. Scholarly views differ.',
    context: 'Used on U.S. jelly beans, candy corn and coated chocolates.',
    kosher: 'Many kosher agencies permit it; not vegan.',
    question: 'Is the glaze insect-derived shellac or a plant wax like carnauba?',
  },
  {
    id: 'vitd3',
    name: 'vitamin D3',
    risk: 'mushbooh',
    aliases: ['vitamin d3', 'cholecalciferol'],
    plain: 'Usually made from lanolin (sheep wool grease); sometimes from fish oil or lichen.',
    context: 'Added to U.S. milk, cereal and margarine.',
    kosher: 'Lanolin D3 is widely accepted; vegan D3 comes from lichen.',
    question: 'Is the vitamin D3 sourced from lanolin, fish oil, or lichen?',
  },
  {
    id: 'cheese',
    name: 'cheese (rennet unknown)',
    risk: 'mushbooh',
    strict: 'oud',
    aliases: [
      'cheese', 'parmesan', 'romano', 'cheddar', 'mozzarella', 'provolone',
      'asiago', 'swiss cheese', 'monterey jack', 'blue cheese', 'cheese powder', 'cheddar cheese powder',
    ],
    exclude: / (vegan|dairy free|plant based|cashew|nutritional yeast) /,
    plain: "Cheese is made with enzymes (rennet). The label doesn't say which kind.",
    context: "Shown only when the label doesn't list the cheese's enzymes separately.",
    kosher: 'OU-D cheese avoids pork rennet.',
    question: 'Is the cheese in this product made with microbial/non-animal rennet?',
  },
];

export const RULES: IngredientRuleDef[] = RAW_RULES.map((r) => ({
  ...r,
  aliasCanon: [...new Set(r.aliases.map((a) => canon(a).trim()))].sort((a, b) => b.length - a.length),
}));

export const RULE_BY_ID: Record<string, IngredientRuleDef> = Object.fromEntries(RULES.map((r) => [r.id, r]));

export const SAFE_Q =
  / (microbial|non animal|animal free|vegetarian|vegan|plant based|plant derived|vegetable|soy derived|palm derived|synthetic|fermentation produced|fungal|bacterial|fish|halal|alcohol free|non alcoholic|carnauba|lichen) /;

export const ANIMAL_Q = / (animal|pork|porcine|calf|lard|tallow|beef|bovine) /;

export const TRUSTED_KOSHER = new Set([
  'OU-D', 'OU-PAREVE', 'OU', 'OK', 'OK-D', 'STAR-K', 'KOF-K', 'CRC', 'OU-P',
]);

export const STATUS_META: Record<StatusKey, { tone: Tone; title: string; short: string }> = {
  certified_halal: { tone: 'halal', title: 'Certified halal', short: 'Certified' },
  verified_plant_or_microbial: { tone: 'ok', title: 'Looks OK', short: 'Looks OK' },
  mushbooh_needs_check: { tone: 'doubt', title: 'Doubtful — check first', short: 'Doubtful' },
  formulation_changed: { tone: 'changed', title: 'Recipe changed', short: 'Changed' },
  animal_or_haram: { tone: 'haram', title: 'Not halal', short: 'Not halal' },
};

export const RES_META: Record<ResolutionKey, { tone: Tone; label: string }> = {
  haram: { tone: 'haram', label: 'Not halal' },
  unresolved: { tone: 'doubt', label: 'Unverified' },
  varies: { tone: 'doubt', label: 'Varies by supplier' },
  expired: { tone: 'doubt', label: 'Expired' },
  recheck: { tone: 'changed', label: 'Re-check' },
  verified: { tone: 'ok', label: 'Confirmed' },
  label: { tone: 'ok', label: 'Label says OK' },
  vegan: { tone: 'ok', label: 'Vegan' },
  policy: { tone: 'ok', label: 'Brand policy' },
  kosher: { tone: 'ok', label: 'Kosher (setting)' },
  cert: { tone: 'halal', label: 'Certified' },
  info: { tone: 'neutral', label: 'Info only' },
};
