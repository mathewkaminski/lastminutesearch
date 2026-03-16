"""Centralized configuration for search filtering and prioritization.

This module contains all keyword patterns and organization lists used for:
- Validating league URLs
- Detecting youth/professional/adult rec leagues
- Prioritizing search results
"""

# Adult rec league positive indicators (boost priority in scoring)
ADULT_REC_KEYWORDS = [
    'adult', 'rec', 'recreational', 'coed', 'co-ed',
    'social', 'beer league', 'mens', 'womens', 'mixed'
]

# Youth organization negative indicators (reject URLs)
YOUTH_INDICATORS = [
    'youth', 'minor', 'junior', 'kids', 'children',
    'u18', 'u16', 'u14', 'u12', 'u10', 'u8', 'u6',
    'district association', 'district soccer', 'district hockey',
    'academy', 'development program', 'rep team', 'house league'
]

# Professional sports patterns (reject URLs - expanded for Canadian leagues)
PROFESSIONAL_PATTERNS = [
    # Major professional leagues
    'mls', 'nba', 'nfl', 'nhl', 'mlb', 'wnba',
    'major league', 'premier league', 'la liga', 'serie a',
    # Canadian professional
    'canpl', 'cpl', 'cfl', 'nll',
    # Professional team indicators
    'toronto fc', 'tfc', 'raptors', 'maple leafs', 'blue jays',
    'whitecaps', 'impact', 'cf montreal', 'cavalry fc',
    # Professional domains
    '.canpl.ca', 'mlssoccer.com', 'nhl.com', 'nba.com',
    # Keywords
    'professional', 'pro team', 'ticket', 'tickets', 'box office'
]

# Known adult rec organizations (expanded - US + Canada)
# Maps domain/organization names to full names for identification
KNOWN_ADULT_REC_ORGS = {
    # US Organizations
    'TSSC': 'Toronto Sport & Social Club',
    'VOLO': 'Volo Sports',
    'ZOGSPORTS': 'ZogSports',
    'JAM': 'JAM Sports',
    'JAMSPORTS': 'JAM Sports',
    'UNDERDOG': 'Underdog Sports',
    'CLUBWAKA': 'Club WAKA',
    'NAKID': 'NAKID Social Sports',
    'PLAYCSA': 'Play CSA',

    # Canadian Organizations
    'OSSC': 'Ottawa Sport & Social Club',
    'OTTAWA': 'Ottawa Sport & Social Club',
    'KSSC': 'Kingston Sport & Social Club',
    'MTLSPORTSOCIAL': 'Montreal Sport Social Club',
    'HFXSPORTSOCIAL': 'Halifax Sport & Social Club',
    'VSSC': 'Vancouver Sport & Social Club',
    'CSSC': 'Calgary Sport & Social Club',
    'ESSC': 'Edmonton Sport & Social Club',
    'SPORTANDSOCIALCLUB': 'Sport & Social Club',
    'CAPITALVOLLEY': 'Capital Volley',
    'OTTAWARECSPORTS': 'Ottawa Rec Sports',
    'OTTAWAVOLLEYSIXES': 'Ottawa Volley Sixes',
    'JAVELINSPORTSINC': 'Javelin Sports Inc',
    'OTTAWAFUSION': 'Ottawa Fusion Volleyball',
    'RACENTRE': 'RA Centre',
    'XTSC': 'Extreme Toronto Sports Club',
    'DOWNTOWNSOCCERTORONTO': 'Downtown Soccer Toronto',
    'TOSOCCERLEAGUE': 'T.O. Soccer League',
    'TOSOCCER': 'TO Soccer',
}
