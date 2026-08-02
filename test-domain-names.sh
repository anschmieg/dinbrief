#!/usr/bin/env bash

names=(
  # Direct letter terms
  letter lettr lttr lett lettre
  epist episto epista epistl
  missiv billet

  # Mail and post
  mail mails mailed mailer
  post postal posted poster
  postel postra postio postly
  maila mailo mailio mailly
  parcel packet

  # Writing and documents
  write writer written
  scribe script scriba scribo
  paper papers papyr papero papera
  page pages paged pager
  folio leaf recto verso
  note notes noted
  memo memos
  draft
  text texter
  prose prosa
  quill ink

  # Folding and paper handling
  fold folded folder
  foldr folda foldio foldly
  form forms formb

  # Sending and delivery
  send sender sent sendr
  sendra sendro
  sealed seal sealer
  stamp stamped
  outbox
  envoy envoya
  enclose
  deliver
  remit

  # Letter conventions
  dear dearly
  hello
  yours
  regard
  salute
  signed
  heading
  subject
  refline
  dateln
  addr
  sender
  rcpt

  # German terms
  brief briefe
  kuvert
  post
  gruss
  anlage
  zeichen
  falten
  falz
  falt
  bogen
  seite
  norm

  # DIN-related abbreviations
  dindoc dinltr
  din500
  formb
  normb
  normlt

  # Abbreviations
  ltr ltrs
  let lett lttr
  msg msgs mssg mssgs
  corr corres
  ep epi
  miv msv
  ml pst psst
  doc docs dcmnt
  txt ppr pg
  fld env envl
  addr adr rcpt sndr
  wrt wrtr scrb

  # Short invented names
  lettra lettri lettry
  letta letto
  letra letro
  postra postel postio
  maila mailo mailio
  folda foldr foldio
  papera papero
  epista episto epistl
  scriba scribo
  sendra sendro
  correa
  misiva
  posta
  carta
  karto
  folia
  folio
  quillo
  inkr
  writr
  pagely
  posty
  mailly
  foldly
)

output_file="available-md-domains.txt"
registered_file="registered-md-domains.txt"
unknown_file="unknown-md-domains.txt"
response_dir="domain-whois-responses"
: > "$output_file"
: > "$registered_file"
: > "$unknown_file"
mkdir -p "$response_dir"

available=0
registered=0
unknown=0
skipped=0

# Remove duplicate names while preserving order.
declare -A seen

for name in "${names[@]}"; do
  [[ -n "${seen[$name]:-}" ]] && continue
  seen[$name]=1

  # Enforce a maximum of seven ASCII characters.
  if (( ${#name} > 7 )); then
    printf '\033[33m%-16s skipped: %d characters\033[0m\n' \
      "$name" "${#name}"
    ((skipped += 1))
    continue
  fi

  domain="${name}.md"
  response_file="$response_dir/$domain.txt"

  # Keep the complete response: connection errors and registry rate limits must
  # never be reported as registered domains.
  whois -h whois.nic.md "$domain" > "$response_file" 2>&1

  if grep -qiE "no match for|no entries found|domain not found" "$response_file"; then
    printf '\033[32m%-16s AVAILABLE\033[0m\n' "$domain"
    printf '%s\n' "$domain" >> "$output_file"
    ((available += 1))
  elif grep -qiE '^domain([[:space:]]+name)?[[:space:]]*:' "$response_file"; then
    printf '\033[31m%-16s already registered\033[0m\n' "$domain"
    printf '%s\n' "$domain" >> "$registered_file"
    ((registered += 1))
  else
    printf '\033[33m%-16s UNKNOWN (rate limit or WHOIS error)\033[0m\n' "$domain"
    printf '%s\n' "$domain" >> "$unknown_file"
    ((unknown += 1))
  fi

  # nic.md starts returning inconclusive responses when queried too quickly.
  sleep "${WHOIS_DELAY:-5}"
done

printf '\n%d available, %d registered, %d unknown, %d skipped\n' \
  "$available" "$registered" "$unknown" "$skipped"
printf 'Available domains: %s\n' "$output_file"
printf 'Unknown domains:   %s\n' "$unknown_file"
