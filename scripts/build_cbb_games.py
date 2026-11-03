"""Build the men's college basketball halftime table: one row per game with the halftime score, the final, the
overtime points, the closing total and spread (home perspective, minus = home favored), and the market's
second-half total where the archive carries one.

Sources (all free, all on GitHub):
  hoopR mbb_schedule_YYYY.csv   ESPN schedules 2008 on (sportsdataverse/sportsdataverse-data, release
                                espn_mens_college_basketball_schedules): finals and the per-half linescores,
                                a neutral-site flag, ESPN's names and abbreviations (the ones the desk's feed
                                carries). YYYY is the year the season ends.
  spreads_and_totals.csv        zachmayer/point_spreads: closing spreads and totals from covers.com (and the
                                SBR archive for the early years), 2010-11 through 2023-24, by date and team name.
  ncaa-basketball-YYYY-YY.xlsx  the sportsbookreviewsonline archive 2007-08 through 2010-11 (in the same repo,
                                data/other_sources): two rows a game (visitor, home) with the half scores, the
                                closing total and spread and the second-half total and spread. These four
                                seasons are the only history with a 2H line, so they carry the model-vs-market
                                study (scripts/fit_cbb.py, section D).

Matching. The SBR rows are matched to ESPN games by date and the scores themselves (half and final, both
teams), which never confuses two schools. The covers rows have no scores, so they match on the date (one day
either way for the late West Coast tips) and the team names, through feeds.norm / feeds.sim (the same matcher
the live desk uses on Kalshi's titles) plus the alias table below for covers' own spellings. A covers row that
fits two ESPN games, or none, is dropped and counted.

Usage: python scripts/build_cbb_games.py SCHED_DIR COVERS.csv SBR_DIR data/cbb_games.csv
       (SCHED_DIR holds mbb_schedule_YYYY.csv, SBR_DIR the four xlsx files)
"""
import csv, os, re, sys, glob, datetime as dt, collections, functools
import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import feeds

# covers.com spellings that feeds.norm does not reach on its own -> the ESPN location name
COVERS_ALIASES = {
    'alaska - anchorage': 'alaska anchorage', 'houston bap': 'houston christian', 'houston baptist': 'houston christian',
    'cs northridge': 'cal state northridge', 'cs fullerton': 'cal state fullerton', 'cs bakersfield': 'cal state bakersfield',
    'cs sacramento': 'sacramento state', 'sacramento st': 'sacramento state', 'cs northridge': 'cal state northridge',
    'nc state': 'nc state', 'n carolina': 'north carolina', 'unc': 'north carolina', 'n carolina st': 'nc state',
    'uconn': 'connecticut', 'conn': 'connecticut', 'umass': 'massachusetts', 'ole miss': 'mississippi',
    'miami fl': 'miami', 'miami (fl)': 'miami', 'miami-florida': 'miami', 'miami oh': 'miami ohio', 'miami (oh)': 'miami ohio',
    'miami-ohio': 'miami ohio', 'pitt': 'pittsburgh', 'lsu': 'lsu', 'usc': 'usc', 'ucf': 'ucf', 'utep': 'utep', 'smu': 'smu',
    'byu': 'byu', 'tcu': 'tcu', 'vcu': 'vcu', 'unlv': 'unlv', 'ucla': 'ucla', 'uab': 'uab', 'utsa': 'utsa', 'fiu': 'fiu',
    'fau': 'florida atlantic', 'fl atlantic': 'florida atlantic', 'fla atlantic': 'florida atlantic', 'fl gulf coast': 'florida gulf coast',
    'fgcu': 'florida gulf coast', 'fl international': 'fiu', 'florida intl': 'fiu', 'fla international': 'fiu',
    'ga southern': 'georgia southern', 'ga tech': 'georgia tech', 'georgia st': 'georgia state', 'ga state': 'georgia state',
    'uc davis': 'uc davis', 'uc irvine': 'uc irvine', 'uc riverside': 'uc riverside', 'uc santa barbara': 'uc santa barbara',
    'ucsb': 'uc santa barbara', 'uc san diego': 'uc san diego', 'cal baptist': 'california baptist', 'cal poly': 'cal poly',
    'cal st fullerton': 'cal state fullerton', 'cal st northridge': 'cal state northridge', 'cal st bakersfield': 'cal state bakersfield',
    'long beach st': 'long beach state', 'lb state': 'long beach state', 'loyola-chicago': 'loyola chicago', 'loyola chi': 'loyola chicago',
    'loyola-maryland': 'loyola maryland', 'loyola md': 'loyola maryland', 'loyola mary': 'loyola maryland', 'loyola marymount': 'loyola marymount',
    'lmu': 'loyola marymount', 'st johns': "st john's", "st. john's": "st john's", 'st josephs': "saint joseph's", "st. joseph's": "saint joseph's",
    'st joseph': "saint joseph's", 'st louis': 'saint louis', 'st. louis': 'saint louis', 'st marys': "saint mary's", "st. mary's": "saint mary's",
    'st peters': "saint peter's", "st. peter's": "saint peter's", 'st bonaventure': 'st bonaventure', 'st francis pa': 'st francis pa',
    'st francis (pa)': 'st francis pa', 'st francis ny': 'st francis brooklyn', 'st francis (ny)': 'st francis brooklyn', 'st francis bkn': 'st francis brooklyn',
    'mt st marys': "mount st mary's", "mt st mary's": "mount st mary's", "mount st. mary's": "mount st mary's", 'mt st mary': "mount st mary's",
    'texas a&m-cc': 'texas a&m corpus christi', 'tx a&m-cc': 'texas a&m corpus christi', 'texas a&m cc': 'texas a&m corpus christi',
    'tx a&m-commerce': 'texas a&m commerce', 'texas a&m-commerce': 'texas a&m commerce', 'east texas a&m': 'east texas a&m',
    'tx southern': 'texas southern', 'texas-arlington': 'ut arlington', 'ut arlington': 'ut arlington', 'texas arlington': 'ut arlington',
    'ut-arlington': 'ut arlington', 'texas-san antonio': 'utsa', 'tx san antonio': 'utsa', 'texas-el paso': 'utep', 'tx el paso': 'utep',
    'texas-pan american': 'ut rio grande valley', 'ut rio grande valley': 'ut rio grande valley', 'utrgv': 'ut rio grande valley',
    'tx rio grande valley': 'ut rio grande valley', 'texas rio grande valley': 'ut rio grande valley', 'texas pan american': 'ut rio grande valley',
    'tx-pan american': 'ut rio grande valley', 'tx pan american': 'ut rio grande valley',
    'se louisiana': 'southeastern louisiana', 'southeast louisiana': 'southeastern louisiana', 'la-lafayette': 'louisiana', 'louisiana-lafayette': 'louisiana',
    'la lafayette': 'louisiana', 'ul lafayette': 'louisiana', 'la-monroe': 'ul monroe', 'louisiana-monroe': 'ul monroe', 'la monroe': 'ul monroe',
    'ul monroe': 'ul monroe', 'ark-pine bluff': 'arkansas pine bluff', 'arkansas-pine bluff': 'arkansas pine bluff', 'ark pine bluff': 'arkansas pine bluff',
    'ark-little rock': 'little rock', 'arkansas-little rock': 'little rock', 'ualr': 'little rock', 'ark little rock': 'little rock',
    'ark state': 'arkansas state', 'app state': 'appalachian state', 'appalachian st': 'appalachian state', 'central conn': 'central connecticut',
    'central conn st': 'central connecticut', 'c connecticut': 'central connecticut', 'cent connecticut': 'central connecticut', 'ccsu': 'central connecticut',
    'central mich': 'central michigan', 'c michigan': 'central michigan', 'cent michigan': 'central michigan', 'western mich': 'western michigan',
    'w michigan': 'western michigan', 'eastern mich': 'eastern michigan', 'e michigan': 'eastern michigan', 'n illinois': 'northern illinois',
    'northern ill': 'northern illinois', 'e illinois': 'eastern illinois', 'w illinois': 'western illinois', 's illinois': 'southern illinois',
    'so illinois': 'southern illinois', 'siu-edwardsville': 'siu edwardsville', 'siu edwardsville': 'siu edwardsville', 'siue': 'siu edwardsville',
    's illinois-edwardsville': 'siu edwardsville', 'e kentucky': 'eastern kentucky', 'w kentucky': 'western kentucky', 'n kentucky': 'northern kentucky',
    'e washington': 'eastern washington', 'wash state': 'washington state', 'e carolina': 'east carolina', 'w carolina': 'western carolina',
    'e tennessee st': 'east tennessee state', 'etsu': 'east tennessee state', 'tenn tech': 'tennessee tech', 'tenn-martin': 'ut martin',
    'tennessee-martin': 'ut martin', 'ut martin': 'ut martin', 'tenn state': 'tennessee state', 'tenn st': 'tennessee state',
    'middle tenn': 'middle tennessee', 'middle tenn st': 'middle tennessee', 'mtsu': 'middle tennessee', 'mid tennessee': 'middle tennessee',
    'n arizona': 'northern arizona', 'n colorado': 'northern colorado', 'n dakota': 'north dakota', 'n dakota st': 'north dakota state',
    's dakota': 'south dakota', 's dakota st': 'south dakota state', 'n iowa': 'northern iowa', 'so miss': 'southern miss', 'southern mississippi': 'southern miss',
    's mississippi': 'southern miss', 'miss state': 'mississippi state', 'miss valley st': 'mississippi valley state', 'ms valley st': 'mississippi valley state',
    'mississippi val': 'mississippi valley state', 'alcorn st': 'alcorn state', 'jackson st': 'jackson state', 'grambling': 'grambling', 'grambling st': 'grambling',
    'prairie view': 'prairie view a&m', 'prairie view a&m': 'prairie view a&m', 'pv a&m': 'prairie view a&m', 'ar-pine bluff': 'arkansas pine bluff',
    'n florida': 'north florida', 'n texas': 'north texas', 'w virginia': 'west virginia', 'virginia military': 'vmi', 'va military': 'vmi',
    'va commonwealth': 'vcu', 'va tech': 'virginia tech', 'geo washington': 'george washington', 'g washington': 'george washington',
    'george wash': 'george washington', 'geo mason': 'george mason', 'g mason': 'george mason', 'james mad': 'james madison', 'jmu': 'james madison',
    'wm & mary': 'william & mary', 'william mary': 'william & mary', 'wm and mary': 'william & mary', 'col of charleston': 'charleston',
    'coll of charleston': 'charleston', 'college of charleston': 'charleston', 'c of charleston': 'charleston', 'charleston so': 'charleston southern',
    'charleston southern': 'charleston southern', 's carolina': 'south carolina', 'sc state': 'south carolina state', 's carolina st': 'south carolina state',
    'sc upstate': 'usc upstate', 'usc upstate': 'usc upstate', 'upstate': 'usc upstate', 'nc central': 'north carolina central', 'n carolina central': 'north carolina central',
    'nc a&t': 'north carolina a&t', 'n carolina a&t': 'north carolina a&t', 'nc-asheville': 'unc asheville', 'unc asheville': 'unc asheville',
    'nc asheville': 'unc asheville', 'nc-wilmington': 'unc wilmington', 'unc wilmington': 'unc wilmington', 'nc wilmington': 'unc wilmington',
    'uncw': 'unc wilmington', 'nc-greensboro': 'unc greensboro', 'unc greensboro': 'unc greensboro', 'nc greensboro': 'unc greensboro', 'uncg': 'unc greensboro',
    'gardner webb': 'gardner-webb', 'gardner-webb': 'gardner-webb', 'presbyterian': 'presbyterian', 'high point': 'high point', 'wofford': 'wofford',
    'fair dickinson': 'fairleigh dickinson', 'f dickinson': 'fairleigh dickinson', 'fdu': 'fairleigh dickinson', 'fairleigh dickinson': 'fairleigh dickinson',
    'liu brooklyn': 'liu', 'liu-brooklyn': 'liu', 'long island': 'liu', 'long island u': 'liu', 'liu': 'liu', 'md-e shore': 'maryland eastern shore',
    'md eastern shore': 'maryland eastern shore', 'maryland-eastern shore': 'maryland eastern shore', 'umes': 'maryland eastern shore',
    'md-baltimore county': 'umbc', 'md baltimore co': 'umbc', 'umbc': 'umbc', 'maryland-baltimore county': 'umbc', 'morgan st': 'morgan state',
    'coppin st': 'coppin state', 'delaware st': 'delaware state', 'norfolk st': 'norfolk state', 'howard': 'howard', 'bethune-cookman': 'bethune-cookman',
    'bethune cookman': 'bethune-cookman', 'b-cookman': 'bethune-cookman', 'florida a&m': 'florida a&m', 'fl a&m': 'florida a&m', 'famu': 'florida a&m',
    'sfa': 'stephen f. austin', 'stephen f austin': 'stephen f. austin', 'stephen f. austin': 'stephen f. austin', 's f austin': 'stephen f. austin',
    'sam houston': 'sam houston', 'sam houston st': 'sam houston', 'nicholls': 'nicholls', 'nicholls st': 'nicholls', 'mcneese': 'mcneese',
    'mcneese st': 'mcneese', 'nw state': 'northwestern state', 'northwestern st': 'northwestern state', 'nw louisiana': 'northwestern state',
    'c arkansas': 'central arkansas', 'cent arkansas': 'central arkansas', 'incarnate word': 'incarnate word', 'uiw': 'incarnate word',
    'new orleans': 'new orleans', 'uno': 'new orleans', 'se missouri st': 'southeast missouri state', 'se missouri': 'southeast missouri state',
    'semo': 'southeast missouri state', 'southeast mo st': 'southeast missouri state', 'e michigan': 'eastern michigan', 'kennesaw': 'kennesaw state',
    'kennesaw st': 'kennesaw state', 'nj tech': 'njit', 'njit': 'njit', 'new jersey tech': 'njit', 'st thomas mn': 'st thomas-minnesota',
    'st thomas (mn)': 'st thomas-minnesota', 'st thomas': 'st thomas-minnesota', 'queens': 'queens university', 'queens nc': 'queens university',
    'queens (nc)': 'queens university', 'lindenwood': 'lindenwood', 'southern ind': 'southern indiana', 's indiana': 'southern indiana',
    'tx a&m-corpus christi': 'texas a&m corpus christi', 'texas a&m-corpus christi': 'texas a&m corpus christi', 'tamu-cc': 'texas a&m corpus christi',
    'utah valley': 'utah valley', 'utah valley st': 'utah valley', 'utah tech': 'utah tech', 'dixie st': 'utah tech', 'dixie state': 'utah tech',
    'tarleton': 'tarleton state', 'tarleton st': 'tarleton state', 'st thomas-minnesota': 'st thomas-minnesota', 'grand canyon': 'grand canyon',
    'cal st-fullerton': 'cal state fullerton', 'csu fullerton': 'cal state fullerton', 'csu northridge': 'cal state northridge', 'csu bakersfield': 'cal state bakersfield',
    'san jose st': 'san jose state', 'san diego st': 'san diego state', 'fresno st': 'fresno state', 'boise st': 'boise state', 'portland st': 'portland state',
    'weber st': 'weber state', 'idaho st': 'idaho state', 'montana st': 'montana state', 'wash st': 'washington state', 'oregon st': 'oregon state',
    'arizona st': 'arizona state', 'colorado st': 'colorado state', 'utah st': 'utah state', 'nm state': 'new mexico state', 'new mexico st': 'new mexico state',
    'n mex state': 'new mexico state', 'nmsu': 'new mexico state', 'kansas st': 'kansas state', 'iowa st': 'iowa state', 'ohio st': 'ohio state',
    'michigan st': 'michigan state', 'penn st': 'penn state', 'florida st': 'florida state', 'oklahoma st': 'oklahoma state', 'texas st': 'texas state',
    'texas state': 'texas state', 'tx state': 'texas state', 'texas-state': 'texas state', 'sw texas st': 'texas state', 'ball st': 'ball state',
    'kent st': 'kent state', 'wright st': 'wright state', 'cleveland st': 'cleveland state', 'youngstown st': 'youngstown state', 'illinois st': 'illinois state',
    'indiana st': 'indiana state', 'missouri st': 'missouri state', 'murray st': 'murray state', 'morehead st': 'morehead state', 'austin peay': 'austin peay',
    'jacksonville st': 'jacksonville state', 'jax state': 'jacksonville state', 'jacksonville': 'jacksonville', 'georgia so': 'georgia southern',
    'ga so': 'georgia southern', 'wichita st': 'wichita state', 'boise state': 'boise state', 's utah': 'southern utah', 'so utah': 'southern utah',
    'detroit': 'detroit mercy', 'detroit mercy': 'detroit mercy', 'ipfw': 'purdue fort wayne', 'fort wayne': 'purdue fort wayne', 'purdue-fort wayne': 'purdue fort wayne',
    'purdue fort wayne': 'purdue fort wayne', 'iupui': 'iu indianapolis', 'iu indy': 'iu indianapolis', 'iu indianapolis': 'iu indianapolis',
    'umkc': 'kansas city', 'kansas city': 'kansas city', 'mo-kansas city': 'kansas city', 'missouri-kc': 'kansas city', 'omaha': 'omaha', 'neb omaha': 'omaha',
    'nebraska-omaha': 'omaha', 'n dakota state': 'north dakota state', 'oral roberts': 'oral roberts', 'w illinois': 'western illinois',
    'st cloud st': 'st cloud state', 'cal st-bakersfield': 'cal state bakersfield', 'nc-charlotte': 'charlotte', 'charlotte': 'charlotte', 'unc charlotte': 'charlotte',
    'nc charlotte': 'charlotte', 'okla state': 'oklahoma state', 'okla st': 'oklahoma state', 'boston col': 'boston college', 'boston coll': 'boston college',
    'bc': 'boston college', 'va': 'virginia', 'cent florida': 'ucf', 'central florida': 'ucf', 'c florida': 'ucf', 'so florida': 'south florida',
    's florida': 'south florida', 'usf': 'south florida', 'so alabama': 'south alabama', 's alabama': 'south alabama', 'n alabama': 'north alabama',
    'alabama a&m': 'alabama a&m', 'ala a&m': 'alabama a&m', 'alabama st': 'alabama state', 'ala state': 'alabama state', 'ala-birmingham': 'uab',
    'alabama-birmingham': 'uab', 'troy st': 'troy', 'troy': 'troy', 'wi-green bay': 'green bay', 'wisconsin-green bay': 'green bay', 'green bay': 'green bay',
    'wisc green bay': 'green bay', 'uw green bay': 'green bay', 'wi-milwaukee': 'milwaukee', 'wisconsin-milwaukee': 'milwaukee', 'milwaukee': 'milwaukee',
    'wisc milwaukee': 'milwaukee', 'uw milwaukee': 'milwaukee', 'ill-chicago': 'uic', 'illinois-chicago': 'uic', 'uic': 'uic', 'il chicago': 'uic',
    'nebraska': 'nebraska', 'neb': 'nebraska', 'mass lowell': 'umass lowell', 'umass-lowell': 'umass lowell', 'umass lowell': 'umass lowell',
    'u mass lowell': 'umass lowell', 'texas-dallas': 'ut dallas', 'army': 'army', 'navy': 'navy', 'air force': 'air force',
    'seattle': 'seattle u', 'seattle u': 'seattle u', 'hawaii': "hawai'i", 'hawaii-hilo': "hawai'i hilo", 'sacred heart': 'sacred heart',
    'mount st marys': "mount st mary's", 'merrimack': 'merrimack', 'le moyne': 'le moyne', 'stonehill': 'stonehill', 'bryant': 'bryant',
    'central ark': 'central arkansas', 'abilene chr': 'abilene christian', 'abilene christian': 'abilene christian', 'acu': 'abilene christian',
    'cent michigan': 'central michigan', 'ill st': 'illinois state', 'ind st': 'indiana state', 'gw': 'george washington', 'uc-irvine': 'uc irvine',
    'uc-davis': 'uc davis', 'uc-riverside': 'uc riverside', 'uc-santa barbara': 'uc santa barbara', 'uc-san diego': 'uc san diego',
    'san fran': 'san francisco', 'san diego': 'san diego', 'st mary': "saint mary's", "st. mary's-ca": "saint mary's", "st mary's ca": "saint mary's",
    "saint mary's (ca)": "saint mary's", "st mary's (ca)": "saint mary's", 'lipscomb': 'lipscomb', 'n florida': 'north florida', 'fl gulf cst': 'florida gulf coast',
    'north florida': 'north florida', 'tx christian': 'tcu', 'texas christian': 'tcu', 'brigham young': 'byu', 'southern cal': 'usc', 'so california': 'usc',
    'southern methodist': 'smu', 'so methodist': 'smu', 'louisiana st': 'lsu', 'la state': 'lsu', 'louisiana state': 'lsu', 'nevada-reno': 'nevada',
    'nevada reno': 'nevada', 'nevada-las vegas': 'unlv', 'nevada las vegas': 'unlv', 'cal-berkeley': 'california', 'cal': 'california', 'california-berkeley': 'california',
    'penn': 'pennsylvania', 'pennsylvania': 'pennsylvania', 'saint josephs': "saint joseph's", 'saint peters': "saint peter's", 'saint louis': 'saint louis',
    'saint marys': "saint mary's", 'saint francis pa': 'st francis pa', 'saint francis': 'st francis pa', 'saint francis ny': 'st francis brooklyn',
    'st francis bkln': 'st francis brooklyn', 'st fran brooklyn': 'st francis brooklyn', 'st francis brooklyn': 'st francis brooklyn',
    'tx-arlington': 'ut arlington', 'tx arlington': 'ut arlington', 'ut-arlington': 'ut arlington', 'houston chr': 'houston christian',
    'southern': 'southern', 'southern u': 'southern', 'southern univ': 'southern', 'tx a&m': 'texas a&m', 'texas a m': 'texas a&m', 'texas am': 'texas a&m',
    'w georgia': 'west georgia', 'west georgia': 'west georgia', 'e texas a&m': 'east texas a&m', 'mercyhurst': 'mercyhurst', 'nc a t': 'north carolina a&t',
    'southern california': 'usc', 'middle tennessee st': 'middle tennessee', 'middle tennessee state': 'middle tennessee', 'monmouth-nj': 'monmouth',
    'monmouth nj': 'monmouth', 'monmouth (nj)': 'monmouth', 'wis-milwaukee': 'milwaukee', 'wis-green bay': 'green bay', 'louisiana monroe': 'ul monroe',
    'indiana-purdue': 'iupui', 'grambling state': 'grambling', 'nicholls state': 'nicholls', 'boston u': 'boston university', 'boston univ': 'boston university',
    'massachusetts lowell': 'umass lowell', 'loyola (md)': 'loyola maryland', 'st francis (bkn)': 'st francis brooklyn', 'md baltimore county': 'umbc',
    'albany': 'ualbany', 'maryland-e shore': 'maryland eastern shore', 'maryland - e shore': 'maryland eastern shore', 'kent': 'kent state',
    'illinois-chicago': 'uic', 'american u': 'american', 'american univ': 'american', 'wku': 'western kentucky', 'nc-wilmington': 'unc wilmington',
    'csu bakersfield': 'cal state bakersfield', 'lamar': 'lamar', 'mcneese state': 'mcneese', 'sam houston state': 'sam houston',
    'stephen f austin': 'stephen f. austin', 'fort wayne': 'purdue fort wayne', 'arkansas-little rock': 'little rock', 'ark-little rock': 'little rock',
    'houston baptist': 'houston christian', 'central connecticut state': 'central connecticut', 'fairleigh dickinson': 'fairleigh dickinson',
    'texas a&m-corpus christi': 'texas a&m corpus christi', 'texas-rio grande valley': 'ut rio grande valley', 'siu-edwardsville': 'siu edwardsville',
    'seattle': 'seattle u', 'hawaii': "hawai'i", 'bethune-cookman': 'bethune-cookman', 'gardner-webb': 'gardner-webb', 'mount st marys': "mount st mary's",
    'saint peters': "saint peter's", 'saint josephs': "saint joseph's", 'st johns': "st john's", 'loyola-chicago': 'loyola chicago', 'loyola chicago': 'loyola chicago',
    'cal st fullerton': 'cal state fullerton', 'cal st northridge': 'cal state northridge', 'cal st bakersfield': 'cal state bakersfield',
    'cs sacramento': 'sacramento state', 'csu sacramento': 'sacramento state', 'sacramento state': 'sacramento state',
    'ulm': 'ul monroe', 'tn martin': 'ut martin', 'loy marymount': 'loyola marymount', 'ull': 'louisiana', 'missouri kc': 'kansas city',
    'cal poly slo': 'cal poly', 'alaska-anchorage': 'alaska anchorage', 'fla gulf coast': 'florida gulf coast',
}


@functools.lru_cache(maxsize=None)
def norm(s):
    """feeds.norm with the covers aliases in front, so both sides land on ESPN's spelling before the desk's own
    normalisation (state -> st, saint -> st, accents dropped)."""
    s0 = re.sub(r'\s+', ' ', str(s or '').strip().lower())
    s0 = s0.replace(' - ', '-').replace('.', '')
    s0 = COVERS_ALIASES.get(s0, s0)
    return feeds.norm(s0)


@functools.lru_cache(maxsize=None)
def sim(a, b):
    """feeds.sim on names already normalised here (it normalises again, which is a no-op); cached because the
    same pair of spellings comes up every time the two schools meet."""
    return feeds.sim(a, b)


def linescores(s):
    """hoopR's linescores string -> [31, 32, ...] by period. Two forms: 2025 on carries the period
    ("[{'displayValue': '31', 'period': 1.0, 'value': 31.0} ...]"), 2023 and 2024 only the values in order
    ("[{'value': 36.0} {'value': 40.0}]"); earlier seasons carry nothing (the play by play fills those, see
    build_cbb_half_scores.py). None when the string is empty or a period is missing."""
    s = str(s or '')
    found = re.findall(r"'period': ([\d.]+), 'value': ([\d.]+)", s)
    if found:
        by = {int(float(p)): int(float(v)) for p, v in found}
        n = max(by)
        if any(i not in by for i in range(1, n + 1)):
            return None
        return [by[i] for i in range(1, n + 1)]
    found = re.findall(r"'value': ([\d.]+)", s)
    return [int(float(v)) for v in found] or None


def read_half_scores(path):
    """build_cbb_half_scores.py's file: game_id -> the play by play's half and final scores."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            out[str(r['game_id'])] = {k: int(r[k]) for k in ('h1a', 'h1h', 'fa', 'fh', 'periods')}
    return out


def read_hoopr(sched_dir, half_path=None):
    """Every ESPN final with a score. The halftime score comes from the schedule's linescores when they are there
    (2023 on) and add up to the final, else from the play by play file when its final agrees with the
    schedule's; a game with neither has h1a / h1h None and can only anchor an SBR row (which brings its own)."""
    pbp = read_half_scores(half_path)
    games = []
    skipped = collections.Counter()
    src = collections.Counter()
    for path in sorted(glob.glob(os.path.join(sched_dir, 'mbb_schedule_*.csv'))):
        with open(path, newline='') as f:
            for r in csv.DictReader(f):
                if r.get('status_type_name') != 'STATUS_FINAL':
                    skipped['not final'] += 1
                    continue
                try:
                    fh, fa = int(r['home_score']), int(r['away_score'])
                except (TypeError, ValueError):
                    skipped['no score'] += 1
                    continue
                if fh + fa < 60:
                    skipped['score too low'] += 1
                    continue
                date = r.get('game_date') or (r.get('game_date_time') or '')[:10]
                if not re.match(r'^\d{4}-\d\d-\d\d$', date or ''):
                    skipped['no date'] += 1
                    continue
                h1a = h1h = ot = periods = None
                lh, la = linescores(r.get('home_linescores')), linescores(r.get('away_linescores'))
                if lh and la and len(lh) >= 2 and len(lh) == len(la) and sum(lh) == fh and sum(la) == fa:
                    h1a, h1h, ot, periods = la[0], lh[0], sum(la[2:]) + sum(lh[2:]), len(lh)
                    src['linescores'] += 1
                else:
                    p = pbp.get(str(r['game_id']))
                    if p and p['fa'] == fa and p['fh'] == fh:
                        h1a, h1h, periods = p['h1a'], p['h1h'], p['periods']
                        ot = None   # the play by play has the period count, not the points by period
                        src['play by play'] += 1
                    else:
                        src['none'] += 1
                games.append(dict(
                    game_id=r['game_id'], season=int(r['season']), season_type=int(r.get('season_type') or 0), date=date,
                    neutral=1 if str(r.get('neutral_site')).lower() == 'true' else 0,
                    away=r['away_location'], home=r['home_location'], away_abbr=r['away_abbreviation'], home_abbr=r['home_abbreviation'],
                    away_norm=sorted({norm(n) for n in (r['away_location'], r['away_display_name'], r['away_short_display_name'])}),
                    home_norm=sorted({norm(n) for n in (r['home_location'], r['home_display_name'], r['home_short_display_name'])}),
                    h1a=h1a, h1h=h1h, fa=fa, fh=fh, ot=ot, periods=periods))
    print(f'hoopR: {len(games)} finals, half score from {dict(src)}; skipped {dict(skipped)}')
    return games


def read_covers(path):
    rows = []
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(dict(date=r['game_date'], home=r['home_team'], away=r['away_team'], spread=float(r['spread']), total=float(r['total'])))
            except (TypeError, ValueError, KeyError):
                continue
    print(f'covers: {len(rows)} lined games')
    return rows


def sbr_date(mmdd, season_start):
    m, d = int(mmdd) // 100, int(mmdd) % 100
    y = season_start if m >= 10 else season_start + 1
    return f'{y:04d}-{m:02d}-{d:02d}'


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_sbr(sbr_dir):
    """The SBR archive: two rows a game. Close and 2H each hold the total on one row and the spread on the other
    (the spread on the favorite's row); the larger of the pair is the total."""
    games = []
    for path in sorted(glob.glob(os.path.join(sbr_dir, 'ncaa-basketball-*.xlsx'))):
        m = re.search(r'(\d{4})-(\d\d)\.xlsx$', path)
        start = int(m.group(1))
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = list(ws.iter_rows(values_only=True))
        head = [str(c).strip() for c in rows[0]]
        ix = {k: head.index(k) for k in ('Date', 'VH', 'Team', '1st', '2nd', 'Final', 'Close', '2H')}
        pairs = 0
        i = 1
        while i + 1 < len(rows):
            a, b = rows[i], rows[i + 1]
            i += 2
            if a[ix['VH']] not in ('V', 'N') or b[ix['VH']] not in ('H', 'N'):
                # the pairing slipped (a stray row): step one row and look again
                i -= 1
                continue
            try:
                h1a, h2a, fa = int(a[ix['1st']]), int(a[ix['2nd']]), int(a[ix['Final']])
                h1h, h2h, fh = int(b[ix['1st']]), int(b[ix['2nd']]), int(b[ix['Final']])
            except (TypeError, ValueError):
                continue
            ca, cb = num(a[ix['Close']]), num(b[ix['Close']])
            total = spread = None
            if ca is not None and cb is not None:
                if ca > cb:
                    total, spread = ca, -cb        # the home row carries the spread: home favored
                else:
                    total, spread = cb, ca         # the visitor is the favorite
            ha, hb = num(a[ix['2H']]), num(b[ix['2H']])
            h2_total = h2_fav = None
            if ha is not None and hb is not None:
                h2_total, h2_fav = max(ha, hb), min(ha, hb)
            games.append(dict(date=sbr_date(a[ix['Date']], start), season=start + 1, away=str(a[ix['Team']]), home=str(b[ix['Team']]),
                              neutral=1 if a[ix['VH']] == 'N' else 0,
                              h1a=h1a, h1h=h1h, fa=fa, fh=fh, ot=max(0, fa - h1a - h2a) + max(0, fh - h1h - h2h),
                              total=total, home_spread=spread, h2_total=h2_total, h2_spread_fav=h2_fav))
            pairs += 1
        print(f'sbr {os.path.basename(path)}: {pairs} games')
    return games


COLS = ['game_id', 'date', 'season', 'season_type', 'neutral', 'away', 'home', 'away_abbr', 'home_abbr', 'h1a', 'h1h', 'fa', 'fh', 'ot', 'periods',
        'total', 'home_spread', 'h2_total', 'h2_spread_fav', 'source']


def main():
    sched_dir, covers_path, sbr_dir, out_path = sys.argv[1:5]
    half_path = sys.argv[5] if len(sys.argv) > 5 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'cbb_half_scores.csv')
    espn = read_hoopr(sched_dir, half_path)
    by_date = collections.defaultdict(list)
    for g in espn:
        by_date[g['date']].append(g)

    def near(date):
        d = dt.date.fromisoformat(date)
        out = []
        for k in (0, -1, 1):
            out += by_date.get((d + dt.timedelta(days=k)).isoformat(), [])
        return out

    taken = {}      # espn game_id -> the line row (and the SBR half score when ESPN has none)
    standalone = []  # SBR games no ESPN final fits, kept on their own names
    # 1. SBR rows: by date and the final score (both teams); the half score must agree when ESPN has one
    sbr = read_sbr(sbr_dir)
    n_sbr = collections.Counter()
    for s in sbr:
        if s['total'] is None:
            n_sbr['no line'] += 1
            continue
        def fits(g, flip):
            fa, fh, h1a, h1h = (s['fh'], s['fa'], s['h1h'], s['h1a']) if flip else (s['fa'], s['fh'], s['h1a'], s['h1h'])
            if (g['fa'], g['fh']) != (fa, fh):
                return False
            return g['h1a'] is None or (g['h1a'], g['h1h']) == (h1a, h1h)
        cands = [g for g in near(s['date']) if fits(g, False)]
        flip = False
        if not cands:
            # a neutral-site game listed with the teams the other way round
            cands = [g for g in near(s['date']) if fits(g, True)]
            flip = True
        if len(cands) > 1:
            # two finals alike within the day either side: the listed date first, then SBR's run-together names
            # ('RhodeIsland', 'CollCharleston') against ESPN's with the spaces taken out
            same = [g for g in cands if g['date'] == s['date']]
            if len(same) == 1:
                cands = same
            else:
                def squash(x):
                    return re.sub(r'[^a-z]', '', str(x).lower())
                sa_, sh_ = (squash(s['home']), squash(s['away'])) if flip else (squash(s['away']), squash(s['home']))
                named = [g for g in (same or cands) if (sa_ and (sa_ in squash(g['away']) or squash(g['away']) in sa_))
                         and (sh_ and (sh_ in squash(g['home']) or squash(g['home']) in sh_))]
                if len(named) == 1:
                    cands = named
        if len(cands) > 1:
            n_sbr['ambiguous'] += 1
            continue
        if not cands:
            n_sbr['standalone'] += 1
            standalone.append(s)
            continue
        g = cands[0]
        if g['game_id'] in taken:
            n_sbr['duplicate'] += 1
            continue
        row = dict(source='sbr', total=s['total'], home_spread=s['home_spread'], h2_total=s['h2_total'], h2_spread_fav=s['h2_spread_fav'])
        if flip:
            row['home_spread'] = None if s['home_spread'] is None else -s['home_spread']
            row.update(h1a=s['h1h'], h1h=s['h1a'], ot=s['ot'])
        else:
            row.update(h1a=s['h1a'], h1h=s['h1h'], ot=s['ot'])
        taken[g['game_id']] = row
        n_sbr['matched'] += 1
    print(f'sbr matched: {dict(n_sbr)}')

    # 2. covers rows: by date and names, onto ESPN games that have a half score
    covers = read_covers(covers_path)
    n_cov = collections.Counter()
    unmatched = collections.Counter()
    for c in covers:
        best, best_s, hits = None, 0.0, 0
        nh, na = norm(c['home']), norm(c['away'])
        for g in near(c['date']):
            sh = max(sim(nh, n) for n in g['home_norm'])
            sa = max(sim(na, n) for n in g['away_norm'])
            if sh < 2.0 or sa < 2.0:
                continue
            s = sh + sa + (0.5 if g['date'] == c['date'] else 0.0)
            if s > best_s:
                best, best_s, hits = g, s, 1
            elif s == best_s:
                hits += 1
        if not best:
            n_cov['no match'] += 1
            unmatched[c['home']] += 1
            unmatched[c['away']] += 1
            continue
        if hits > 1:
            n_cov['ambiguous'] += 1
            continue
        if best['game_id'] in taken:
            n_cov['already lined (sbr)'] += 1
            continue
        if best['h1a'] is None:
            n_cov['no half score'] += 1
            continue
        taken[best['game_id']] = dict(source='covers', total=c['total'], home_spread=c['spread'], h2_total=None, h2_spread_fav=None)
        n_cov['matched'] += 1
    print(f'covers matched: {dict(n_cov)}')
    print('covers names with no ESPN game (top 60):', unmatched.most_common(60))

    # 3. write every lined game: ESPN's names and ids, the half score from ESPN (or SBR's when ESPN has none)
    n = 0
    by_season = collections.Counter()
    with open(out_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for g in sorted(espn, key=lambda g: (g['date'], g['game_id'])):
            line = taken.get(g['game_id'])
            if not line:
                continue
            row = {k: g[k] for k in COLS if k in g}
            if row.get('h1a') is None:
                row.update(h1a=line['h1a'], h1h=line['h1h'], ot=line['ot'])
            row.update(total=line['total'], home_spread=line['home_spread'], h2_total=line['h2_total'], h2_spread_fav=line['h2_spread_fav'], source=line['source'])
            w.writerow({k: ('' if v is None else v) for k, v in row.items()})
            n += 1
            by_season[g['season']] += 1
        for s in sorted(standalone, key=lambda s: s['date']):
            row = dict(game_id='', date=s['date'], season=s['season'], season_type='', neutral=s['neutral'], away=s['away'], home=s['home'], away_abbr='', home_abbr='',
                       h1a=s['h1a'], h1h=s['h1h'], fa=s['fa'], fh=s['fh'], ot=s['ot'], periods='', total=s['total'], home_spread=s['home_spread'],
                       h2_total=s['h2_total'], h2_spread_fav=s['h2_spread_fav'], source='sbr-only')
            w.writerow({k: ('' if v is None else v) for k, v in row.items()})
            n += 1
            by_season[s['season']] += 1
    print(f'{n} lined games written to {out_path}; by season {dict(sorted(by_season.items()))}')


if __name__ == '__main__':
    main()
